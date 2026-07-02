import uuid
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.organizations.models import OrganizationMember
from src.projects.models import Project
from src.tasks.models import Task, TaskComment, TaskStatusHistory


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_accessible_task(
        self, task_id: uuid.UUID, user_id: uuid.UUID
    ) -> Task | None:
        result = await self.session.execute(
            select(Task)
            .join(Project, Project.id == Task.project_id)
            .join(
                OrganizationMember,
                OrganizationMember.organization_id == Project.organization_id,
            )
            .where(Task.id == task_id, OrganizationMember.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_project(
        self, project_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[Task]:
        result = await self.session.execute(
            select(Task)
            .join(Project, Project.id == Task.project_id)
            .join(
                OrganizationMember,
                OrganizationMember.organization_id == Project.organization_id,
            )
            .where(Task.project_id == project_id, OrganizationMember.user_id == user_id)
            .order_by(Task.position.asc(), Task.created_at.asc())
        )
        return list(result.scalars().all())

    async def add_task(self, task: Task) -> Task:
        self.session.add(task)
        await self.session.flush()
        await self.session.refresh(task)
        return task

    async def update_task_optimistic(
        self,
        task_id: uuid.UUID,
        expected_version: int,
        values: dict[str, object],
    ) -> bool:
        result = await self.session.execute(
            update(Task)
            .where(Task.id == task_id, Task.version == expected_version)
            .values(**values, version=Task.version + 1)
        )
        rowcount = getattr(result, "rowcount", 0)
        return cast("bool", rowcount == 1)

    async def add_comment(self, comment: TaskComment) -> TaskComment:
        self.session.add(comment)
        await self.session.flush()
        await self.session.refresh(comment)
        return comment

    async def list_comments(
        self, task_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[TaskComment]:
        task = await self.session.execute(
            select(TaskComment)
            .join(Task, Task.id == TaskComment.task_id)
            .join(Project, Project.id == Task.project_id)
            .join(
                OrganizationMember,
                OrganizationMember.organization_id == Project.organization_id,
            )
            .where(
                TaskComment.task_id == task_id, OrganizationMember.user_id == user_id
            )
            .order_by(TaskComment.created_at.asc())
        )
        return list(task.scalars().all())

    async def add_history(self, history: TaskStatusHistory) -> TaskStatusHistory:
        self.session.add(history)
        await self.session.flush()
        await self.session.refresh(history)
        return history

    async def list_history(
        self, task_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[TaskStatusHistory]:
        task = await self.get_accessible_task(task_id, user_id)
        if task is None:
            return []
        result = await self.session.execute(
            select(TaskStatusHistory)
            .where(TaskStatusHistory.task_id == task_id)
            .order_by(TaskStatusHistory.created_at.asc())
        )
        return list(result.scalars().all())
