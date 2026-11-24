"""Task storage and business rules, shared by the web UI and the JSON API."""
from datetime import datetime
from typing import Literal, get_args

from app import users, webhooks
from app.audit import log_event
from app.db import get_conn
from app.errors import ValidationError

Status = Literal["To Do", "In Progress", "In Review", "Done"]
STATUSES = get_args(Status)

TITLE_MAX = 200


class TaskNotFound(Exception):
    def __init__(self, task_id):
        super().__init__(f"Task {task_id} not found")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean(value, field, *, required=False, max_len=None):
    value = (value or "").strip()
    if required and not value:
        raise ValidationError(f"{field} is required")
    if max_len and len(value) > max_len:
        raise ValidationError(f"{field} must be at most {max_len} characters")
    return value


def _check_status(status):
    if status not in STATUSES:
        raise ValidationError(f"Status must be one of: {', '.join(STATUSES)}")
    return status


def _check_assignee(assignee):
    """Blank means unassigned; otherwise it must be a registered user (stored with their exact username)."""
    if not assignee:
        return ""
    user = users.find_user(assignee)
    if user is None:
        raise ValidationError(f"Assignee '{assignee}' is not a registered user")
    return user["username"]


def _log(conn, task_id, actor, message, at):
    conn.execute(
        "INSERT INTO history (task_id, actor, message, created_at) VALUES (?, ?, ?, ?)",
        (task_id, actor, message, at),
    )


def _webhook_task(task):
    """The task fields sent in webhook events (not its comments or history)."""
    return {k: task[k] for k in ("id", "title", "description", "status", "creator", "assignee", "created_at", "updated_at")}


def _describe_change(field, old, new):
    if field == "description":
        return "Description updated"
    if field == "assignee":
        old, new = old or "Unassigned", new or "Unassigned"
    return f"{field.capitalize()} changed from '{old}' to '{new}'"


def create_task(title, creator, description="", assignee="", status="To Do"):
    title = _clean(title, "Title", required=True, max_len=TITLE_MAX)
    creator = _clean(creator, "Creator", required=True)
    assignee = _check_assignee(_clean(assignee, "Assignee"))
    description = _clean(description, "Description")
    status = _check_status(status)
    now = _now()
    with get_conn() as conn:
        # RETURNING hands back the new row's id; works in both SQLite and PostgreSQL.
        task_id = conn.execute(
            """INSERT INTO tasks (title, description, status, creator, assignee, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id""",
            (title, description, status, creator, assignee, now, now),
        ).fetchone()["id"]
        _log(conn, task_id, creator, f"Ticket created on {now} by {creator}", now)
    log_event("task_created", creator, task_id=task_id, title=title, status=status, assignee=assignee or "-")
    task = get_task(task_id)
    webhooks.emit("task.created", {"task": _webhook_task(task)}, creator)
    return task


def list_tasks(status=None, assignee=None):
    query = "SELECT * FROM tasks"
    clauses, params = [], []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if assignee:
        # lower() on both sides: case-insensitive in both databases (PostgreSQL's LIKE is case-sensitive).
        clauses.append("lower(assignee) LIKE lower(?)")
        params.append(f"%{assignee.strip()}%")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id DESC"
    with get_conn() as conn:
        return [dict(row) for row in conn.execute(query, params)]


def get_task(task_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise TaskNotFound(task_id)
        task = dict(row)
        task["comments"] = [
            dict(r) for r in conn.execute("SELECT * FROM comments WHERE task_id = ? ORDER BY id", (task_id,))
        ]
        task["history"] = [
            dict(r) for r in conn.execute("SELECT * FROM history WHERE task_id = ? ORDER BY id", (task_id,))
        ]
    return task


def update_task(task_id, actor, title=None, description=None, status=None, assignee=None):
    """Apply the given changes (None = leave as is) and log one history entry per changed field."""
    current = get_task(task_id)

    changes = {}
    if title is not None:
        changes["title"] = _clean(title, "Title", required=True, max_len=TITLE_MAX)
    if description is not None:
        changes["description"] = _clean(description, "Description")
    if status is not None:
        changes["status"] = _check_status(status)
    if assignee is not None:
        assignee = _clean(assignee, "Assignee")
        # Only check new values, so tasks still assigned to a deleted user can be edited.
        changes["assignee"] = _check_assignee(assignee) if assignee != current["assignee"] else assignee
    changes = {field: value for field, value in changes.items() if value != current[field]}
    if not changes:
        return current

    now = _now()
    with get_conn() as conn:
        # Column names come from the fixed keys above, never from user input.
        assignments = ", ".join(f"{field} = ?" for field in changes)
        conn.execute(
            f"UPDATE tasks SET {assignments}, updated_at = ? WHERE id = ?",
            (*changes.values(), now, task_id),
        )
        for field, new in changes.items():
            _log(conn, task_id, actor, _describe_change(field, current[field], new), now)
    # Field names only; the old/new values are in the task's own history.
    log_event("task_updated", actor, task_id=task_id, fields=",".join(changes))
    task = get_task(task_id)
    webhooks.emit("task.updated", {"task": _webhook_task(task), "changed_fields": list(changes)}, actor)
    return task


def delete_task(task_id, deleted_by=None):
    with get_conn() as conn:
        row = conn.execute("DELETE FROM tasks WHERE id = ? RETURNING title", (task_id,)).fetchone()
        if row is None:
            raise TaskNotFound(task_id)
    # The task and its history are gone after this, so the log is the only record of who deleted it.
    log_event("task_deleted", deleted_by, task_id=task_id, title=row["title"])
    webhooks.emit("task.deleted", {"task": {"id": task_id, "title": row["title"]}}, deleted_by)


def status_counts():
    with get_conn() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status").fetchall()
        found = {row["status"]: row["n"] for row in rows}
    return {status: found.get(status, 0) for status in STATUSES}


def add_comment(task_id, author, body):
    body = _clean(body, "Comment", required=True)
    now = _now()
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone() is None:
            raise TaskNotFound(task_id)
        comment = conn.execute(
            "INSERT INTO comments (task_id, author, body, created_at) VALUES (?, ?, ?, ?) RETURNING *",
            (task_id, author, body, now),
        ).fetchone()
        conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", (now, task_id))
        _log(conn, task_id, author, "Comment added", now)
    log_event("comment_added", author, task_id=task_id, comment_id=comment["id"])  # never the comment text
    webhooks.emit("comment.added", {"task_id": task_id, "comment": dict(comment)}, author)
    return dict(comment)
