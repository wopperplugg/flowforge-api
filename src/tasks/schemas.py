import uuid
from datetime import date, datetime

from pydantic import Field, model_validator

from src.common.enums import TaskPriority, TaskStatus
from src.common.schemas import BaseSchema, TimestampSchema


class TaskCreate(BaseSchema):
    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    assigned_to_id: uuid.UUID | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: date | None = None


class TaskUpdate(BaseSchema):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    assigned_to_id: uuid.UUID | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_date: date | None = None
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def ensure_at_least_one_editable_field(self) -> "TaskUpdate":
        if (
            self.title is None
            and self.description is None
            and self.assigned_to_id is None
            and self.status is None
            and self.priority is None
            and self.due_date is None
        ):
            raise ValueError("At least one task field must be provided")
        return self


class TaskResponse(TimestampSchema):
    id: uuid.UUID
    project_id: uuid.UUID
    created_by_id: uuid.UUID
    assigned_to_id: uuid.UUID | None
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    position: int
    due_date: date | None
    version: int


class TaskCommentCreate(BaseSchema):
    text: str = Field(min_length=1, max_length=5000)


class TaskCommentResponse(TimestampSchema):
    id: uuid.UUID
    task_id: uuid.UUID
    author_id: uuid.UUID
    text: str


class TaskStatusHistoryResponse(BaseSchema):
    id: uuid.UUID
    task_id: uuid.UUID
    changed_by_id: uuid.UUID
    old_status: TaskStatus | None
    new_status: TaskStatus
    created_at: datetime
