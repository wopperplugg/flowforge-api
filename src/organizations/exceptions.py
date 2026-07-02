from src.common.exceptions import AppError


class OrganizationNotFoundError(AppError):
    code = "organization_not_found"
    message = "Organization was not found"
    status_code = 404


class OrganizationAlreadyExistsError(AppError):
    code = "organization_already_exists"
    message = "Organization with this slug already exists"
    status_code = 409
