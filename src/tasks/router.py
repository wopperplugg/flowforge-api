import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from src.auth.dependencies import get_current_user
from src.common.dependencies import DbSession
from src.tasks.schemas import (
    TaskCommentCreate,
    TaskCommentResponse,
    TaskCreate,
    TaskResponse,
    TaskStatusHistoryResponse,
    TaskUpdate,
)
from src.tasks.service import TaskService
from src.users.models import User

router = APIRouter(tags=["tasks"])


def get_task_service(session: DbSession) -> TaskService:
    return TaskService(session)


@router.post(
    "/api/v1/projects/{project_id}/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    project_id: uuid.UUID,
    payload: TaskCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    task_service: Annotated[TaskService, Depends(get_task_service)],
) -> TaskResponse:
    task = await task_service.create_task(project_id, payload, current_user)
    return TaskResponse.model_validate(task)


@router.get("/api/v1/projects/{project_id}/tasks", response_model=list[TaskResponse])
async def list_tasks(
    project_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    task_service: Annotated[TaskService, Depends(get_task_service)],
) -> list[TaskResponse]:
    tasks = await task_service.list_tasks(project_id, current_user)
    return [TaskResponse.model_validate(task) for task in tasks]


@router.get("/api/v1/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    task_service: Annotated[TaskService, Depends(get_task_service)],
) -> TaskResponse:
    task = await task_service.get_task(task_id, current_user)
    return TaskResponse.model_validate(task)


@router.patch("/api/v1/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    task_service: Annotated[TaskService, Depends(get_task_service)],
) -> TaskResponse:
    task = await task_service.update_task(task_id, payload, current_user)
    return TaskResponse.model_validate(task)


@router.post(
    "/api/v1/tasks/{task_id}/comments",
    response_model=TaskCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_comment(
    task_id: uuid.UUID,
    payload: TaskCommentCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    task_service: Annotated[TaskService, Depends(get_task_service)],
) -> TaskCommentResponse:
    comment = await task_service.add_comment(task_id, payload, current_user)
    return TaskCommentResponse.model_validate(comment)


@router.get(
    "/api/v1/tasks/{task_id}/comments",
    response_model=list[TaskCommentResponse],
)
async def list_comments(
    task_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    task_service: Annotated[TaskService, Depends(get_task_service)],
) -> list[TaskCommentResponse]:
    comments = await task_service.list_comments(task_id, current_user)
    return [TaskCommentResponse.model_validate(comment) for comment in comments]


@router.get(
    "/api/v1/tasks/{task_id}/history",
    response_model=list[TaskStatusHistoryResponse],
)
async def list_history(
    task_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    task_service: Annotated[TaskService, Depends(get_task_service)],
) -> list[TaskStatusHistoryResponse]:
    history = await task_service.list_history(task_id, current_user)
    return [TaskStatusHistoryResponse.model_validate(item) for item in history]
