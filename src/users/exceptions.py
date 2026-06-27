from src.common.exceptions import AppError

class UserNotFoundError(AppError):
    code = "user_not_found"
    message = "User was not found"
    status_code = 404

class UserAlreadyExistsError(AppError):
    code = "user_alredy_exists"
    message = "User with this email or username already exists"
    status_code = 409