from src.common.exceptions import AppError


class TaskNotFoundError(AppError):
    code = "task_not_found"
    message = "Task was not found"
    status_code = 404


class TaskVersionConflictError(AppError):
    code = "task_version_conflict"
    message = "Task was changed by another user"
    status_code = 409
