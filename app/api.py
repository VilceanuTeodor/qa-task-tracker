"""JSON API under /api. Interactive docs are served at /docs.

Log in with POST /api/auth/login, then send the token as `Authorization: Bearer <token>`.
"""
from fastapi import APIRouter, Depends, HTTPException, Response

from app import ai, debug, tasks, users
from app.auth import api_admin, api_token, api_user
from app.errors import ValidationError
from app.schemas import (
    Comment,
    CommentCreate,
    Credentials,
    HistoryEntry,
    LoginResponse,
    RoleUpdate,
    Stats,
    Task,
    TaskCreate,
    TaskDetail,
    TaskUpdate,
    TitleSuggestion,
    TitleSuggestionRequest,
    User,
    UserSummary,
)
from app.tasks import Status

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
router = APIRouter(prefix="/api", tags=["tasks"], dependencies=[Depends(api_user)])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(api_admin)])


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (tasks.TaskNotFound, users.UserNotFound) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


def suggest_title_or_http_error(description, username):
    """Shared by the API and the web page: maps AI errors to HTTP status codes."""
    try:
        return ai.suggest_title(description, actor=username)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ai.AINotConfigured:
        raise HTTPException(status_code=503, detail="AI suggestions are not configured on this server")
    except ai.AIRateLimited as e:
        raise HTTPException(status_code=429, detail=f"Too many suggestions, try again in {e.retry_after} seconds",
                            headers={"Retry-After": str(e.retry_after)})
    except ai.AIUnavailable as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- auth ---

@auth_router.post("/signup", response_model=User, status_code=201)
def signup(payload: Credentials):
    return _run(users.create_user, payload.username, payload.password)


@auth_router.post("/login", response_model=LoginResponse)
def login(payload: Credentials):
    user = users.authenticate(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"access_token": users.create_session(user["id"]), "user": user}


@auth_router.post("/logout", status_code=204, dependencies=[Depends(api_user)])
def logout(token=Depends(api_token)):
    users.delete_session(token)
    return Response(status_code=204)


@auth_router.get("/me", response_model=User)
def me(user=Depends(api_user)):
    return user


# --- tasks (any signed-in user) ---

@router.get("/users", response_model=list[UserSummary], tags=["users"])
def list_users():
    return users.list_users()


@router.get("/tasks", response_model=list[Task])
def list_tasks(status: Status | None = None, assignee: str | None = None):
    return tasks.list_tasks(status=status, assignee=assignee)


@router.post("/tasks", response_model=TaskDetail, status_code=201)
def create_task(payload: TaskCreate, user=Depends(api_user)):
    return _run(tasks.create_task, creator=user["username"], **payload.model_dump())


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def get_task(task_id: int):
    return _run(tasks.get_task, task_id)


@router.patch("/tasks/{task_id}", response_model=TaskDetail)
def update_task(task_id: int, payload: TaskUpdate, user=Depends(api_user)):
    return _run(tasks.update_task, task_id, user["username"], **payload.model_dump(exclude_unset=True))


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, admin=Depends(api_admin)):
    """Admin only."""
    _run(tasks.delete_task, task_id, deleted_by=admin["username"])
    return Response(status_code=204)


@router.get("/tasks/{task_id}/comments", response_model=list[Comment])
def list_comments(task_id: int):
    return _run(tasks.get_task, task_id)["comments"]


@router.post("/tasks/{task_id}/comments", response_model=Comment, status_code=201)
def add_comment(task_id: int, payload: CommentCreate, user=Depends(api_user)):
    return _run(tasks.add_comment, task_id, user["username"], payload.body)


@router.post("/ai/suggest-title", response_model=TitleSuggestion, tags=["ai"],
             summary="Suggest a task title from a description (Claude)")
def suggest_title(payload: TitleSuggestionRequest, user=Depends(api_user)):
    """Rate limited per user. 503 if AI isn't configured, 429 if over the limit, 502 if the AI call fails."""
    return {"title": suggest_title_or_http_error(payload.description, user["username"])}


@router.get("/tasks/{task_id}/history", response_model=list[HistoryEntry])
def get_history(task_id: int):
    return _run(tasks.get_task, task_id)["history"]


# --- admin ---

@admin_router.get("/users", response_model=list[User])
def admin_list_users():
    return users.list_users()


@admin_router.patch("/users/{user_id}", response_model=User)
def admin_set_role(user_id: int, payload: RoleUpdate, admin=Depends(api_admin)):
    return _run(users.set_role, user_id, payload.role, admin["id"])


@admin_router.delete("/users/{user_id}", status_code=204)
def admin_delete_user(user_id: int, admin=Depends(api_admin)):
    _run(users.delete_user, user_id, admin["id"])
    return Response(status_code=204)


@admin_router.get("/debug/sentry-error", summary="Trigger a test error (checks Sentry)")
def debug_sentry_error():
    """Crashes on purpose with a ZeroDivisionError, so you can follow it in Sentry. Admin only."""
    debug.trigger_test_error()


@admin_router.get("/stats", response_model=Stats)
def admin_stats():
    counts = tasks.status_counts()
    return {"total_tasks": sum(counts.values()), "tasks_by_status": counts, "total_users": len(users.list_users())}
