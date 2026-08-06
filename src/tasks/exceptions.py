from src.common.exceptions import AppError


class TaskNotFoundError(AppError):
    code = "task_not_found"
    message = "Task was not found"
    status_code = 404


class TaskVersionConflictError(AppError):
    code = "task_version_conflict"
    message = "Task was changed by another user"
    status_code = 409


class TaskAssigneeNotOrganizationMemberError(AppError):
    code = "task_assignee_not_organization_member"
    message = "Task assignee must be a member of the project organization"
    status_code = 400
