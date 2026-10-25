"""Creating, reading, updating and deleting tasks through the JSON API."""
import re

import pytest

from support import unique_name


def test_create_task(user, admin):
    res = user.api.post("/api/tasks", json={
        "title": "Login button does nothing",
        "description": "Click Sign in, nothing happens",
        "assignee": user.username,
        "status": "In Progress",
    })

    assert res.status_code == 201
    task = res.json()
    assert task["title"] == "Login button does nothing"
    assert task["status"] == "In Progress"
    assert task["assignee"] == user.username
    assert task["creator"] == user.username, "creator comes from the token"
    assert task["comments"] == []
    admin.delete(f"/api/tasks/{task['id']}")


def test_new_task_history_starts_with_ticket_created(task, user):
    first = task["history"][0]["message"]

    assert re.fullmatch(r"Ticket created on \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} by " + user.username, first)


def test_new_task_defaults(task):
    assert task["status"] == "To Do"
    assert task["assignee"] == ""
    assert task["description"] == ""


@pytest.mark.parametrize("payload, message", [
    ({"title": "   "}, "Title is required"),
    ({"title": "x" * 201}, "at most 200"),
    ({"title": "Ghost", "assignee": "no_such_user_123"}, "not a registered user"),
])
def test_create_task_rejects_invalid_input(user, payload, message):
    res = user.api.post("/api/tasks", json=payload)

    assert res.status_code == 422
    assert message in res.json()["detail"]


@pytest.mark.parametrize("payload", [
    {},                                  # no title at all
    {"title": "Bad status", "status": "Blocked"},
])
def test_create_task_rejects_bad_fields(user, payload):
    assert user.api.post("/api/tasks", json=payload).status_code == 422


def test_get_task(user, task):
    res = user.api.get(f"/api/tasks/{task['id']}")

    assert res.status_code == 200
    assert res.json()["title"] == task["title"]


def test_get_missing_task_returns_404(user):
    assert user.api.get("/api/tasks/999999").status_code == 404


def test_list_tasks_includes_new_task(user, task):
    ids = [t["id"] for t in user.api.get("/api/tasks").json()]

    assert task["id"] in ids


def test_list_tasks_filter_by_status(user, admin):
    done = user.api.post("/api/tasks", json={"title": unique_name("Done"), "status": "Done"}).json()
    todo = user.api.post("/api/tasks", json={"title": unique_name("Todo")}).json()

    tasks = user.api.get("/api/tasks", params={"status": "Done"}).json()

    assert all(t["status"] == "Done" for t in tasks)
    ids = [t["id"] for t in tasks]
    assert done["id"] in ids and todo["id"] not in ids
    for t in (done, todo):
        admin.delete(f"/api/tasks/{t['id']}")


def test_update_status_is_recorded_in_history(user, task):
    res = user.api.patch(f"/api/tasks/{task['id']}", json={"status": "In Review"})

    assert res.status_code == 200
    updated = res.json()
    assert updated["status"] == "In Review"
    last = updated["history"][-1]
    assert last["message"] == "Status changed from 'To Do' to 'In Review'"
    assert last["actor"] == user.username


def test_update_only_changes_the_fields_sent(user, task):
    updated = user.api.patch(f"/api/tasks/{task['id']}", json={"description": "New details"}).json()

    assert updated["description"] == "New details"
    assert updated["title"] == task["title"]
    assert updated["status"] == task["status"]
    assert updated["history"][-1]["message"] == "Description updated"


def test_update_with_the_same_value_adds_no_history(user, task):
    updated = user.api.patch(f"/api/tasks/{task['id']}", json={"status": "To Do"}).json()

    assert len(updated["history"]) == len(task["history"])


def test_assign_and_unassign(user, task):
    assigned = user.api.patch(f"/api/tasks/{task['id']}", json={"assignee": user.username.upper()}).json()
    assert assigned["assignee"] == user.username, "assignee is stored with the real username's casing"

    unassigned = user.api.patch(f"/api/tasks/{task['id']}", json={"assignee": ""}).json()
    assert unassigned["assignee"] == ""
    assert unassigned["history"][-1]["message"] == f"Assignee changed from '{user.username}' to 'Unassigned'"


def test_update_missing_task_returns_404(user):
    assert user.api.patch("/api/tasks/999999", json={"status": "Done"}).status_code == 404


def test_regular_user_cannot_delete_a_task(user, task):
    res = user.api.delete(f"/api/tasks/{task['id']}")

    assert res.status_code == 403
    assert user.api.get(f"/api/tasks/{task['id']}").status_code == 200, "task must still exist"


def test_admin_can_delete_a_task(user, admin):
    created = user.api.post("/api/tasks", json={"title": unique_name("Delete me")}).json()

    assert admin.delete(f"/api/tasks/{created['id']}").status_code == 204
    assert user.api.get(f"/api/tasks/{created['id']}").status_code == 404
    assert admin.delete(f"/api/tasks/{created['id']}").status_code == 404, "deleting twice is a 404"
