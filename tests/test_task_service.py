import uuid
from datetime import UTC, datetime

import pytest

from src.common.enums import OutboxStatus, TaskPriority, TaskStatus
from src.common.pagination import PaginationParams
from src.outbox.models import OutboxEvent
from src.projects.exceptions import ProjectNotFoundError
from src.projects.models import Project
from src.tasks.exceptions import TaskVersionConflictError
from src.tasks.models import Task, TaskStatusHistory
from src.tasks.schemas import TaskCreate, TaskUpdate
from src.tasks.service import TaskService
from src.users.models import User
from tests.fakes import FakeSession


class FakeProjectRepository:
    def __init__(self, project: Project | None) -> None:
        self.project = project

    async def get_accessible_project(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Project | None:
        if self.project is None or self.project.id != project_id:
            return None
        return self.project


class FakeTaskRepository:
    def __init__(self, task: Task | None = None, update_succeeds: bool = True) -> None:
        self.task = task
        self.update_succeeds = update_succeeds
        self.created_tasks: list[Task] = []
        self.history: list[TaskStatusHistory] = []
        self.optimistic_updates: list[tuple[uuid.UUID, int, dict[str, object]]] = []
        self.list_calls: list[tuple[uuid.UUID, uuid.UUID, int, int]] = []

    async def add_task(self, task: Task) -> Task:
        task.id = uuid.uuid4()
        self.created_tasks.append(task)
        self.task = task
        return task

    async def add_history(self, history: TaskStatusHistory) -> TaskStatusHistory:
        history.id = uuid.uuid4()
        self.history.append(history)
        return history

    async def get_accessible_task(
        self,
        task_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Task | None:
        if self.task is None or self.task.id != task_id:
            return None
        return self.task

    async def update_task_optimistic(
        self,
        task_id: uuid.UUID,
        expected_version: int,
        values: dict[str, object],
    ) -> bool:
        self.optimistic_updates.append((task_id, expected_version, values))
        if not self.update_succeeds or self.task is None:
            return False
        for key, value in values.items():
            setattr(self.task, key, value)
        self.task.version += 1
        return True

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[Task], int]:
        self.list_calls.append((project_id, user_id, limit, offset))
        if self.task is None or self.task.project_id != project_id:
            return [], 0
        return [self.task], 1


def make_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="owner@example.com",
        username="owner",
        hashed_password="hash",
    )


def make_project() -> Project:
    return Project(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        name="Backend",
        key="API",
    )


def make_service(
    *,
    project: Project | None,
    task: Task | None = None,
    update_succeeds: bool = True,
) -> tuple[TaskService, FakeSession, FakeTaskRepository]:
    session = FakeSession()
    service = TaskService(session)  # type: ignore[arg-type]
    task_repository = FakeTaskRepository(task=task, update_succeeds=update_succeeds)
    service.projects = FakeProjectRepository(project)  # type: ignore[assignment]
    service.tasks = task_repository  # type: ignore[assignment]
    return service, session, task_repository


@pytest.mark.asyncio
async def test_create_task_creates_history_and_outbox_event_atomically() -> None:
    user = make_user()
    project = make_project()
    service, session, task_repository = make_service(project=project)

    task = await service.create_task(
        project.id,
        TaskCreate(title="Ship API", priority=TaskPriority.HIGH),
        user,
    )

    assert task in task_repository.created_tasks
    assert task.project_id == project.id
    assert task.created_by_id == user.id
    assert task.status == TaskStatus.TODO
    assert task.version == 1

    assert len(task_repository.history) == 1
    assert task_repository.history[0].old_status is None
    assert task_repository.history[0].new_status == TaskStatus.TODO

    assert len(session.added) == 1
    event = session.added[0]
    assert isinstance(event, OutboxEvent)
    assert event.aggregate_id == task.id
    assert event.event_type == "task.created"
    assert event.status == OutboxStatus.PENDING
    assert event.payload == {"task_id": str(task.id), "project_id": str(project.id)}


@pytest.mark.asyncio
async def test_create_task_denies_inaccessible_project_without_side_effects() -> None:
    user = make_user()
    service, session, task_repository = make_service(project=None)

    with pytest.raises(ProjectNotFoundError):
        await service.create_task(uuid.uuid4(), TaskCreate(title="Hidden task"), user)

    assert task_repository.created_tasks == []
    assert task_repository.history == []
    assert session.added == []


@pytest.mark.asyncio
async def test_list_tasks_returns_paginated_response() -> None:
    user = make_user()
    project = make_project()
    created_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    updated_at = datetime(2026, 1, 2, 3, 5, 6, tzinfo=UTC)
    task = Task(
        id=uuid.uuid4(),
        project_id=project.id,
        created_by_id=user.id,
        title="Review API",
        status=TaskStatus.TODO,
        priority=TaskPriority.MEDIUM,
        position=0,
        version=1,
        created_at=created_at,
        updated_at=updated_at,
    )
    service, _, task_repository = make_service(project=project, task=task)

    page = await service.list_tasks(
        project.id,
        user,
        PaginationParams(limit=20, offset=0),
    )

    assert page.model_dump(mode="json") == {
        "items": [
            {
                "id": str(task.id),
                "project_id": str(project.id),
                "created_by_id": str(user.id),
                "assigned_to_id": None,
                "title": "Review API",
                "description": None,
                "status": "todo",
                "priority": "medium",
                "position": 0,
                "due_date": None,
                "version": 1,
                "created_at": "2026-01-02T03:04:05Z",
                "updated_at": "2026-01-02T03:05:06Z",
            }
        ],
        "total": 1,
        "limit": 20,
        "offset": 0,
    }
    assert task_repository.list_calls == [(project.id, user.id, 20, 0)]


@pytest.mark.asyncio
async def test_list_tasks_returns_empty_paginated_response() -> None:
    user = make_user()
    project = make_project()
    service, _, _ = make_service(project=project)

    page = await service.list_tasks(
        project.id,
        user,
        PaginationParams(),
    )

    assert page.model_dump(mode="json") == {
        "items": [],
        "total": 0,
        "limit": 20,
        "offset": 0,
    }


@pytest.mark.asyncio
async def test_update_task_status_uses_optimistic_lock_and_emits_event() -> None:
    user = make_user()
    project = make_project()
    task = Task(
        id=uuid.uuid4(),
        project_id=project.id,
        created_by_id=user.id,
        title="Review API",
        status=TaskStatus.TODO,
        priority=TaskPriority.MEDIUM,
        position=0,
        version=3,
    )
    service, session, task_repository = make_service(project=project, task=task)

    updated = await service.update_task(
        task.id,
        TaskUpdate(status=TaskStatus.REVIEW, version=3),
        user,
    )

    assert updated.status == TaskStatus.REVIEW
    assert updated.version == 4
    assert task_repository.optimistic_updates == [
        (task.id, 3, {"status": TaskStatus.REVIEW})
    ]
    assert len(task_repository.history) == 1
    assert task_repository.history[0].old_status == TaskStatus.TODO
    assert task_repository.history[0].new_status == TaskStatus.REVIEW

    event = session.added[0]
    assert isinstance(event, OutboxEvent)
    assert event.event_type == "task.status_changed"
    assert event.payload["old_status"] == "todo"
    assert event.payload["new_status"] == "review"


@pytest.mark.asyncio
async def test_update_task_version_conflict_has_no_history_or_outbox() -> None:
    user = make_user()
    project = make_project()
    task = Task(
        id=uuid.uuid4(),
        project_id=project.id,
        created_by_id=user.id,
        title="Review API",
        status=TaskStatus.TODO,
        priority=TaskPriority.MEDIUM,
        position=0,
        version=4,
    )
    service, session, task_repository = make_service(
        project=project,
        task=task,
        update_succeeds=False,
    )

    with pytest.raises(TaskVersionConflictError):
        await service.update_task(
            task.id,
            TaskUpdate(status=TaskStatus.DONE, version=3),
            user,
        )

    assert task.status == TaskStatus.TODO
    assert task_repository.history == []
    assert session.added == []
