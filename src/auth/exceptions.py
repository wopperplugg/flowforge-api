

class AuthError(Exception):
    """base auth exception"""
    def __init__(self, message: str = "Authentication failed"):
        self.message = message
        super().__init__(self.message)

class InvalidCredentialsError(AuthError):
    def __init__(self, message: str = "Invalid email or password"):
        super().__init__(message)

class InvalidTokenError(AuthError):
    def __init__(self, message: str = "Invalid token"):
        super().__init__(message)

class ExpiredTokenError(AuthError):
    def __init__(self, message: str = "Token has expired"):
        super().__init__(message)

class InvalidTokenTypeError(AuthError):
    def __init__ (self, message: str = "Invalid token type"):
        super().__init__(message)

class InactiveUserError(AuthError):
    def __init__(self, message: str = "User account is inactive"):
        super().__init__(message)


class RateLimitExceededError(AuthError):
    def __init__(self, message: str = "Too many attempts. Try again later"):
        super().__init__(message)


class UserAlreadyExistsError(AuthError):
    def __init__(self, message: str = "User with this email or username already exists"):
        super().__init__(message)