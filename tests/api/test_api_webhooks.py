"""Outgoing webhooks, end to end: the app (sender) -> a fake receiver we control.

The test app retries after 0.5 s and 1 s (3 attempts in total) and waits at most 1 s for an answer,
so outages can be tested in seconds. In production the waits are 10 s, 1 min, 5 min, 30 min.
"""
import json
import time

import pytest

from app.webhooks import verify
from support import unique_name

ATTEMPTS = 3   # 1 try + 2 retries (WEBHOOK_RETRY_DELAYS="0.5,1" in conftest)


def wait_for(check, timeout=15, what="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {what}")


@pytest.fixture
def hook(admin, receiver):
    """A webhook pointing at the fake receiver; removed after the test."""
    res = admin.post("/api/admin/webhooks", json={"url": receiver.url})
    assert res.status_code == 201
    created = res.json()
    yield created
    admin.delete(f"/api/admin/webhooks/{created['id']}")


def deliveries(admin, hook):
    return admin.get(f"/api/admin/webhooks/{hook['id']}/deliveries?limit=50").json()


def delivery(admin, hook, event_id=None, status=None, event=None, delivery_id=None):
    """The first delivery in the log matching all the given values, or None."""
    for d in deliveries(admin, hook):
        if ((event_id is None or d["event_id"] == event_id) and (status is None or d["status"] == status)
                and (event is None or d["event"] == event) and (delivery_id is None or d["id"] == delivery_id)):
            return d
    return None


def create_task(user):
    res = user.api.post("/api/tasks", json={"title": unique_name("Hook task")})
    assert res.status_code == 201
    return res.json()


# --- managing webhooks -----------------------------------------------------------------

def test_only_admins_can_manage_webhooks(user):
    assert user.api.get("/api/admin/webhooks").status_code == 403
    assert user.api.post("/api/admin/webhooks", json={"url": "https://example.com"}).status_code == 403


@pytest.mark.parametrize("body", [
    {"url": "ftp://example.com/hook"},
    {"url": "not a url"},
    {"url": "https://example.com/" + "a" * 600},
    {"url": "https://example.com/hook", "events": ["task.exploded"]},
])
def test_invalid_webhooks_are_rejected(admin, body):
    assert admin.post("/api/admin/webhooks", json=body).status_code == 422


def test_secret_is_shown_only_when_created(admin, hook):
    assert hook["secret"].startswith("whsec_")
    listed = [h for h in admin.get("/api/admin/webhooks").json() if h["id"] == hook["id"]][0]
    assert "secret" not in listed


# --- happy path ------------------------------------------------------------------------

def test_task_created_is_delivered_signed_and_logged(admin, user, receiver, hook):
    task = create_task(user)
    request = wait_for(lambda: receiver.received("task.created", task_id=task["id"]), what="task.created")[0]

    headers, body = request["headers"], request["body"]
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Webhook-Event"] == "task.created"
    assert headers["X-Webhook-Attempt"] == "1"
    assert headers["X-Webhook-Id"].startswith("evt_")
    # The receiver can prove the request came from us and wasn't changed:
    assert verify(hook["secret"], headers["X-Webhook-Timestamp"], body, headers["X-Webhook-Signature"])
    assert not verify(hook["secret"], headers["X-Webhook-Timestamp"], body.replace("Hook", "Fake"),
                      headers["X-Webhook-Signature"])

    event = json.loads(body)
    assert event["actor"] == user.username
    assert event["data"]["task"]["title"] == task["title"]
    assert "comments" not in event["data"]["task"]

    logged = wait_for(lambda: delivery(admin, hook, event_id=headers["X-Webhook-Id"], status="succeeded"),
                      what="delivery marked succeeded")
    assert logged["attempts"] == 1 and logged["last_status_code"] == 200


def test_update_comment_and_delete_events(admin, user, receiver, hook):
    task = create_task(user)
    user.api.patch(f"/api/tasks/{task['id']}", json={"status": "Done"})
    user.api.post(f"/api/tasks/{task['id']}/comments", json={"body": "Looks good"})
    admin.delete(f"/api/tasks/{task['id']}")

    updated = wait_for(lambda: receiver.received("task.updated", task_id=task["id"]), what="task.updated")[0]
    assert updated["json"]["data"]["changed_fields"] == ["status"]
    assert updated["json"]["data"]["task"]["status"] == "Done"
    comment = wait_for(lambda: receiver.received("comment.added", task_id=task["id"]), what="comment.added")[0]
    assert comment["json"]["data"]["comment"]["body"] == "Looks good"
    deleted = wait_for(lambda: receiver.received("task.deleted", task_id=task["id"]), what="task.deleted")[0]
    assert deleted["json"]["actor"] == "admin"


def test_send_test_event(admin, receiver, hook):
    assert admin.post(f"/api/admin/webhooks/{hook['id']}/test").status_code == 202
    wait_for(lambda: receiver.received("webhook.test"), what="webhook.test")


def test_events_can_be_filtered(admin, user, receiver):
    only_deletes = admin.post("/api/admin/webhooks", json={"url": receiver.url, "events": ["task.deleted"]}).json()
    try:
        task = create_task(user)
        admin.delete(f"/api/tasks/{task['id']}")
        wait_for(lambda: receiver.received("task.deleted", task_id=task["id"]), what="task.deleted")
        assert receiver.received("task.created", task_id=task["id"]) == []
    finally:
        admin.delete(f"/api/admin/webhooks/{only_deletes['id']}")


# --- when the receiving side has problems --------------------------------------------------

def test_receiver_errors_are_retried_until_it_recovers(admin, user, receiver, hook):
    receiver.status = 500                      # receiver is broken
    task = create_task(user)
    wait_for(lambda: len(receiver.received("task.created", task_id=task["id"])) >= 2, what="a retry")

    receiver.status = 200                      # receiver is fixed before the last attempt
    event_id = receiver.received("task.created", task_id=task["id"])[0]["headers"]["X-Webhook-Id"]
    done = wait_for(lambda: delivery(admin, hook, event_id=event_id, status="succeeded"),
                    what="delivery to succeed after the receiver recovered")

    sent = receiver.received("task.created", task_id=task["id"])
    assert [r["headers"]["X-Webhook-Attempt"] for r in sent] == [str(i) for i in range(1, len(sent) + 1)]
    assert len({r["headers"]["X-Webhook-Id"] for r in sent}) == 1     # same event id on every retry
    assert len({r["body"] for r in sent}) == 1                         # identical body on every retry
    assert done["attempts"] == len(sent) and done["last_status_code"] == 200


def test_receiver_down_does_not_affect_users_and_is_recorded(admin, user, receiver, hook):
    receiver.stop()                            # nothing listens on the URL any more

    started = time.monotonic()
    task = create_task(user)                   # the user's action still works, without waiting
    assert time.monotonic() - started < 2

    failed = wait_for(lambda: delivery(admin, hook, event="task.created", status="failed"), what="delivery to give up")
    assert failed["attempts"] == ATTEMPTS
    assert failed["last_status_code"] is None
    assert "Connection failed" in failed["last_error"] or "Timed out" in failed["last_error"]

    # Receiver comes back: an admin redelivers, and this time it arrives.
    receiver.start()
    admin.post(f"/api/admin/webhook-deliveries/{failed['id']}/redeliver")
    wait_for(lambda: receiver.received("task.created", task_id=task["id"]), what="redelivery")
    done = wait_for(lambda: delivery(admin, hook, delivery_id=failed["id"], status="succeeded"),
                    what="redelivery marked succeeded")
    assert done["attempts"] == 1


def test_slow_receiver_times_out_and_is_retried(admin, user, receiver, hook):
    receiver.delay = 2                         # longer than the 1 s timeout
    task = create_task(user)
    slow = wait_for(lambda: next((d for d in deliveries(admin, hook)
                                  if d["event"] == "task.created" and d["attempts"] >= 1 and d["last_error"]), None),
                    what="a timed-out attempt")
    assert "Timed out" in slow["last_error"]
    receiver.delay = 0
    wait_for(lambda: delivery(admin, hook, delivery_id=slow["id"], status="succeeded"),
             what="success once the receiver is fast again")
    assert receiver.received("task.created", task_id=task["id"])


def test_deleting_a_webhook_stops_its_deliveries(admin, user, receiver):
    created = admin.post("/api/admin/webhooks", json={"url": receiver.url}).json()
    assert admin.delete(f"/api/admin/webhooks/{created['id']}").status_code == 204
    task = create_task(user)
    time.sleep(1)
    assert receiver.received("task.created", task_id=task["id"]) == []
    assert admin.get(f"/api/admin/webhooks/{created['id']}/deliveries").status_code == 404
