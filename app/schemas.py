"""Request/response models for the JSON API (these also drive the Swagger docs)."""
from pydantic import BaseModel, Field

from app.tasks import Status
from app.users import Role


class Credentials(BaseModel):
    username: str
    password: str


class User(BaseModel):
    id: int
    username: str
    role: Role
    created_at: str


class UserSummary(BaseModel):
    id: int
    username: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: User


class RoleUpdate(BaseModel):
    role: Role


class Stats(BaseModel):
    total_tasks: int
    tasks_by_status: dict[str, int]
    total_users: int


class TaskCreate(BaseModel):
    title: str
    description: str = ""
    assignee: str = ""
    status: Status = "To Do"


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: Status | None = None
    assignee: str | None = None


class CommentCreate(BaseModel):
    body: str


class Comment(BaseModel):
    id: int
    task_id: int
    author: str
    body: str
    created_at: str


class HistoryEntry(BaseModel):
    id: int
    task_id: int
    actor: str
    message: str
    created_at: str


class Task(BaseModel):
    id: int
    title: str
    description: str
    status: Status
    creator: str
    assignee: str
    created_at: str
    updated_at: str


class TaskDetail(Task):
    comments: list[Comment]
    history: list[HistoryEntry]


class TitleSuggestionRequest(BaseModel):
    description: str
    # Titles already suggested (or typed) for this task, so Claude can offer a different one.
    previous: list[str] = Field(default_factory=list, max_length=20)


class TitleSuggestion(BaseModel):
    title: str
