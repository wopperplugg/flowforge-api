from src.common.exceptions import AppError


class ProjectNotFoundError(AppError):
    code = "project_not_found"
    message = "Project was not found"
    status_code = 404


class ProjectAlreadyExistsError(AppError):
    code = "project_already_exists"
    message = "Project with this key already exists in organization"
    status_code = 409
