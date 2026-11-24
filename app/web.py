"""Server-rendered HTML pages."""
import os
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import ai, tasks, users, webhooks
from app.auth import SESSION_COOKIE, optional_user, require_admin, require_user
from app.errors import ValidationError
from app.schemas import TitleSuggestionRequest

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")
# Templates only learn WHETHER AI is on (to show the button), never the key itself.
templates.env.globals["ai_enabled"] = ai.is_enabled


def render(request, name, user, status_code=200, **context):
    return templates.TemplateResponse(
        request, name, {"statuses": tasks.STATUSES, "user": user, **context}, status_code=status_code
    )


def _error(request, user, status_code, heading, message):
    return render(request, "error.html", user, status_code=status_code, heading=heading, message=message)


def _not_found(request, user, message):
    return _error(request, user, 404, "Not found", message)


def _safe_next(target):
    # Only local paths, so the login page can't be used to bounce people to another site.
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


def _start_session(user_id, target):
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        users.create_session(user_id),
        max_age=int(users.SESSION_LIFETIME.total_seconds()),
        httponly=True,
        samesite="lax",
        # COOKIE_SECURE=true (set on the HTTPS deployment): the browser only sends the
        # session cookie over HTTPS. Off by default so http://127.0.0.1 keeps working.
        secure=os.environ.get("COOKIE_SECURE", "").lower() == "true",
    )
    return response


def _usernames():
    return [u["username"] for u in users.list_users()]


# --- sign up / sign in ---

@router.get("/login")
def login_form(request: Request, next_url: str = Query("/", alias="next"), user=Depends(optional_user)):
    if user:
        return RedirectResponse("/", status_code=303)
    return render(request, "login.html", None, next=_safe_next(next_url), form={}, error=None)


@router.post("/login")
def login(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next_url: str = Form("/", alias="next"),
):
    user = users.authenticate(username, password)
    if user is None:
        return render(
            request, "login.html", None, status_code=401,
            next=_safe_next(next_url), form={"username": username}, error="Invalid username or password",
        )
    return _start_session(user["id"], _safe_next(next_url))


@router.get("/signup")
def signup_form(request: Request, user=Depends(optional_user)):
    if user:
        return RedirectResponse("/", status_code=303)
    return render(request, "signup.html", None, form={}, error=None)


@router.post("/signup")
def signup(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    confirm_password: str = Form(""),
):
    try:
        if password != confirm_password:
            raise ValidationError("Passwords don't match")
        user = users.create_user(username, password)
    except ValidationError as e:
        return render(request, "signup.html", None, status_code=422, form={"username": username}, error=str(e))
    return _start_session(user["id"], "/")


@router.post("/logout")
def logout(request: Request):
    users.delete_session(request.cookies.get(SESSION_COOKIE))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


# --- tasks ---

def _detail(request, user, task_id, status_code=200, comment_error=None, comment_form=None):
    try:
        task = tasks.get_task(task_id)
    except tasks.TaskNotFound as e:
        return _not_found(request, user, f"{e}.")
    return render(
        request, "detail.html", user, status_code=status_code,
        task=task, comment_error=comment_error, comment_form=comment_form or {},
    )


@router.get("/")
def index(request: Request, status: str = "", assignee: str = "", user=Depends(require_user)):
    items = tasks.list_tasks(status=status or None, assignee=assignee or None)
    return render(request, "list.html", user, tasks=items, status_filter=status, assignee_filter=assignee)


@router.get("/tasks/new")
def new_task_form(request: Request, user=Depends(require_user)):
    return render(request, "form.html", user, editing=False, task=None, form={}, usernames=_usernames(), error=None)


@router.post("/tasks/suggest-title")
def suggest_title(payload: TitleSuggestionRequest, user=Depends(require_user)):
    """Called by the "Suggest title" button (JSON in, JSON out). Claude is called here, on the server."""
    from app.api import suggest_title_or_http_error  # shared error mapping
    return {"title": suggest_title_or_http_error(payload.description, user["username"], payload.previous)}


@router.post("/tasks")
def create_task(
    request: Request,
    title: str = Form(""),
    description: str = Form(""),
    assignee: str = Form(""),
    status: str = Form("To Do"),
    user=Depends(require_user),
):
    form = {"title": title, "description": description, "assignee": assignee, "status": status}
    try:
        task = tasks.create_task(creator=user["username"], **form)
    except ValidationError as e:
        return render(
            request, "form.html", user, status_code=422,
            editing=False, task=None, form=form, usernames=_usernames(), error=str(e),
        )
    return RedirectResponse(f"/tasks/{task['id']}", status_code=303)


@router.get("/tasks/{task_id}")
def task_detail(request: Request, task_id: int, user=Depends(require_user)):
    return _detail(request, user, task_id)


@router.get("/tasks/{task_id}/edit")
def edit_task_form(request: Request, task_id: int, user=Depends(require_user)):
    try:
        task = tasks.get_task(task_id)
    except tasks.TaskNotFound as e:
        return _not_found(request, user, f"{e}.")
    return render(request, "form.html", user, editing=True, task=task, form=task, usernames=_usernames(), error=None)


@router.post("/tasks/{task_id}/edit")
def edit_task(
    request: Request,
    task_id: int,
    title: str = Form(""),
    description: str = Form(""),
    status: str = Form(""),
    assignee: str = Form(""),
    user=Depends(require_user),
):
    form = {"title": title, "description": description, "status": status, "assignee": assignee}
    try:
        tasks.update_task(task_id, user["username"], **form)
    except tasks.TaskNotFound as e:
        return _not_found(request, user, f"{e}.")
    except ValidationError as e:
        return render(
            request, "form.html", user, status_code=422,
            editing=True, task=tasks.get_task(task_id), form=form, usernames=_usernames(), error=str(e),
        )
    return RedirectResponse(f"/tasks/{task_id}", status_code=303)


@router.post("/tasks/{task_id}/delete")
def delete_task(request: Request, task_id: int, user=Depends(require_admin)):
    try:
        tasks.delete_task(task_id, deleted_by=user["username"])
    except tasks.TaskNotFound as e:
        return _not_found(request, user, f"{e}.")
    return RedirectResponse("/", status_code=303)


@router.post("/tasks/{task_id}/comments")
def add_comment(request: Request, task_id: int, body: str = Form(""), user=Depends(require_user)):
    try:
        tasks.add_comment(task_id, user["username"], body)
    except tasks.TaskNotFound as e:
        return _not_found(request, user, f"{e}.")
    except ValidationError as e:
        return _detail(request, user, task_id, status_code=422, comment_error=str(e), comment_form={"body": body})
    return RedirectResponse(f"/tasks/{task_id}#comments", status_code=303)


# --- admin ---

def _admin_page(request, user, status_code=200, error=None):
    counts = tasks.status_counts()
    return render(
        request, "admin.html", user, status_code=status_code,
        accounts=users.list_users(), counts=counts, total_tasks=sum(counts.values()), error=error,
    )


@router.get("/admin")
def admin_dashboard(request: Request, user=Depends(require_admin)):
    return _admin_page(request, user)


def _webhooks_page(request, user, status_code=200, error=None, created=None):
    hooks = [{**h, "deliveries": webhooks.list_deliveries(h["id"], limit=10)} for h in webhooks.list_webhooks()]
    return render(request, "webhooks.html", user, status_code=status_code,
                  hooks=hooks, events=webhooks.EVENTS, error=error, created=created)


@router.get("/admin/webhooks")
def admin_webhooks(request: Request, user=Depends(require_admin)):
    return _webhooks_page(request, user)


@router.post("/admin/webhooks")
def admin_add_webhook(request: Request, url: str = Form(""), user=Depends(require_admin)):
    try:
        created = webhooks.create_webhook(url, user["username"])
    except ValidationError as e:
        return _webhooks_page(request, user, status_code=422, error=str(e))
    return _webhooks_page(request, user, created=created)   # shows the secret once


@router.post("/admin/webhooks/{webhook_id}/test")
def admin_test_webhook(request: Request, webhook_id: int, user=Depends(require_admin)):
    try:
        webhooks.send_test(webhook_id, user["username"])
    except webhooks.WebhookNotFound as e:
        return _not_found(request, user, f"{e}.")
    return RedirectResponse("/admin/webhooks", status_code=303)


@router.post("/admin/webhooks/{webhook_id}/delete")
def admin_delete_webhook(request: Request, webhook_id: int, user=Depends(require_admin)):
    try:
        webhooks.delete_webhook(webhook_id, user["username"])
    except webhooks.WebhookNotFound as e:
        return _not_found(request, user, f"{e}.")
    return RedirectResponse("/admin/webhooks", status_code=303)


@router.post("/admin/webhook-deliveries/{delivery_id}/redeliver")
def admin_redeliver(request: Request, delivery_id: int, user=Depends(require_admin)):
    try:
        webhooks.redeliver(delivery_id, user["username"])
    except webhooks.DeliveryNotFound as e:
        return _not_found(request, user, f"{e}.")
    return RedirectResponse("/admin/webhooks", status_code=303)


@router.post("/admin/users/{user_id}/role")
def admin_set_role(request: Request, user_id: int, role: str = Form(""), user=Depends(require_admin)):
    try:
        users.set_role(user_id, role, user["id"])
    except users.UserNotFound as e:
        return _not_found(request, user, f"{e}.")
    except ValidationError as e:
        return _admin_page(request, user, status_code=422, error=str(e))
    return RedirectResponse("/admin", status_code=303)


@router.post("/admin/users/{user_id}/delete")
def admin_delete_user(request: Request, user_id: int, user=Depends(require_admin)):
    try:
        users.delete_user(user_id, user["id"])
    except users.UserNotFound as e:
        return _not_found(request, user, f"{e}.")
    except ValidationError as e:
        return _admin_page(request, user, status_code=422, error=str(e))
    return RedirectResponse("/admin", status_code=303)
