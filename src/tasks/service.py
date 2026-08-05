import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.common.enums import OutboxStatus, TaskStatus
from src.common.pagination import Page, PaginationParams
from src.outbox.models import OutboxEvent
from src.projects.exceptions import ProjectNotFoundError
from src.projects.repository import ProjectRepository
from src.tasks.exceptions import TaskNotFoundError, TaskVersionConflictError
from src.tasks.models import Task, TaskComment, TaskStatusHistory
from src.tasks.repository import TaskRepository
from src.tasks.schemas import TaskCommentCreate, TaskCreate, TaskResponse, TaskUpdate
from src.users.models import User


class TaskService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.tasks = TaskRepository(session)

    async def create_task(
        self, project_id: uuid.UUID, data: TaskCreate, user: User
    ) -> Task:
        async with self._transaction():
            project = await self.projects.get_accessible_project(project_id, user.id)
            if project is None:
                raise ProjectNotFoundError()

            task = await self.tasks.add_task(
                Task(
                    project_id=project_id,
                    created_by_id=user.id,
                    assigned_to_id=data.assigned_to_id,
                    title=data.title,
                    description=data.description,
                    status=TaskStatus.TODO,
                    priority=data.priority,
                    due_date=data.due_date,
                    position=0,
                    version=1,
                )
            )
            await self.tasks.add_history(
                TaskStatusHistory(
                    task_id=task.id,
                    changed_by_id=user.id,
                    old_status=None,
                    new_status=task.status,
                    created_at=datetime.now(UTC),
                )
            )
            self.session.add(
                OutboxEvent(
                    aggregate_type="task",
                    aggregate_id=task.id,
                    event_type="task.created",
                    payload={"task_id": str(task.id), "project_id": str(project_id)},
                    status=OutboxStatus.PENDING,
                    attempts=0,
                )
            )
            return task

    async def list_tasks(
        self,
        project_id: uuid.UUID,
        user: User,
        pagination: PaginationParams,
    ) -> Page[TaskResponse]:
        tasks, total = await self.tasks.list_for_project(
            project_id,
            user.id,
            limit=pagination.limit,
            offset=pagination.offset,
        )
        return Page[TaskResponse](
            items=[TaskResponse.model_validate(task) for task in tasks],
            total=total,
            limit=pagination.limit,
            offset=pagination.offset,
        )

    async def get_task(self, task_id: uuid.UUID, user: User) -> Task:
        task = await self.tasks.get_accessible_task(task_id, user.id)
        if task is None:
            raise TaskNotFoundError()
        return task

    async def update_task(
        self, task_id: uuid.UUID, data: TaskUpdate, user: User
    ) -> Task:
        async with self._transaction():
            task = await self.tasks.get_accessible_task(task_id, user.id)
            if task is None:
                raise TaskNotFoundError()

            values = data.model_dump(exclude={"version"}, exclude_none=True)
            old_status = task.status
            updated = await self.tasks.update_task_optimistic(
                task_id, data.version, values
            )
            if not updated:
                raise TaskVersionConflictError()

            await self.session.refresh(task)
            if data.status is not None and data.status != old_status:
                await self.tasks.add_history(
                    TaskStatusHistory(
                        task_id=task.id,
                        changed_by_id=user.id,
                        old_status=old_status,
                        new_status=data.status,
                        created_at=datetime.now(UTC),
                    )
                )
                self.session.add(
                    OutboxEvent(
                        aggregate_type="task",
                        aggregate_id=task.id,
                        event_type="task.status_changed",
                        payload={
                            "task_id": str(task.id),
                            "project_id": str(task.project_id),
                            "old_status": old_status.value,
                            "new_status": data.status.value,
                        },
                        status=OutboxStatus.PENDING,
                        attempts=0,
                    )
                )
            return task

    async def add_comment(
        self,
        task_id: uuid.UUID,
        data: TaskCommentCreate,
        user: User,
    ) -> TaskComment:
        async with self._transaction():
            task = await self.tasks.get_accessible_task(task_id, user.id)
            if task is None:
                raise TaskNotFoundError()
            return await self.tasks.add_comment(
                TaskComment(task_id=task.id, author_id=user.id, text=data.text)
            )

    async def list_comments(self, task_id: uuid.UUID, user: User) -> list[TaskComment]:
        task = await self.tasks.get_accessible_task(task_id, user.id)
        if task is None:
            raise TaskNotFoundError()
        return await self.tasks.list_comments(task_id, user.id)

    async def list_history(
        self, task_id: uuid.UUID, user: User
    ) -> list[TaskStatusHistory]:
        task = await self.tasks.get_accessible_task(task_id, user.id)
        if task is None:
            raise TaskNotFoundError()
        return await self.tasks.list_history(task_id, user.id)

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        if self.session.in_transaction():
            yield
            return
        async with self.session.begin():
            yield
