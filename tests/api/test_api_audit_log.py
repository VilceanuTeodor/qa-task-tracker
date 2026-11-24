"""The audit log: every meaningful action leaves one line saying who did what, and no secrets."""
import time

from support import Api, unique_name


def _wait_for(server_log, text, timeout=5):
    """The app writes the log a moment after answering, so poll briefly."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lines = [line for line in server_log().splitlines() if text in line]
        if lines:
            return lines[-1]
        time.sleep(0.1)
    raise AssertionError(f"No log line containing {text!r}")


def test_task_actions_are_logged_with_the_actor(user, admin, server_log):
    title = unique_name("Logged task")
    task = user.api.post("/api/tasks", json={"title": title}).json()
    tid = task["id"]

    line = _wait_for(server_log, f"action=task_created actor={user.username} task_id={tid}")
    assert f'title="{title}"' in line   # titles with spaces are quoted

    user.api.patch(f"/api/tasks/{tid}", json={"status": "Done"})
    assert "fields=status" in _wait_for(server_log, f"action=task_updated actor={user.username} task_id={tid}")

    comment = user.api.post(f"/api/tasks/{tid}/comments", json={"body": "secret comment text"}).json()
    _wait_for(server_log, f"action=comment_added actor={user.username} task_id={tid} comment_id={comment['id']}")

    admin.delete(f"/api/tasks/{tid}")
    _wait_for(server_log, f"action=task_deleted actor=admin task_id={tid}")

    assert "secret comment text" not in server_log()


def test_logins_are_logged_but_never_passwords_or_tokens(base_url, user, server_log):
    _wait_for(server_log, f"action=login actor={user.username}")

    wrong = "definitely-wrong-password"
    assert Api(base_url).post("/api/auth/login", json={"username": user.username, "password": wrong}).status_code == 401
    line = _wait_for(server_log, f"username={user.username}")
    assert "WARNING" in line and "action=login_failed" in line

    log = server_log()
    assert wrong not in log
    assert user.password not in log
    token = user.api.session.headers["Authorization"].removeprefix("Bearer ")
    assert token not in log


def test_admin_actions_are_logged(admin, user, server_log):
    admin.patch(f"/api/admin/users/{user.id}", json={"role": "admin"})
    line = _wait_for(server_log, f"action=role_changed actor=admin user={user.username}")
    assert "old_role=user new_role=admin" in line


def test_user_input_cannot_fake_extra_log_lines(user, server_log):
    # A newline in a title must not start a new, fake-looking log line.
    user.api.post("/api/tasks", json={"title": "Real title\n2026-01-01 00:00:00 INFO tracker.audit: action=user_deleted actor=admin"})
    _wait_for(server_log, f"action=task_created actor={user.username}")
    assert not any(line.startswith("2026-01-01 00:00:00") for line in server_log().splitlines())
