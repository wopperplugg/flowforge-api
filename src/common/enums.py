from enum import StrEnum

class UserRole(StrEnum):
    USER ="user"
    MODERATOR="moderator"
    ASMIN="admin"

class OrganizationRole(StrEnum):
    OWNER="owner"
    ADMIN="admin"
    MEMBER="member"
    VIEWER="viewer"

class TaskStatus(StrEnum):
    TODO="todo"
    IN_PROGRESS="in_progress"
    REVIEw="review"
    DONE="done"
    CANCELED="canceled"

class TaskPriority(StrEnum):
    LOW="low"
    MEDIUM="medium"
    HIGH="high"
    CRITICAL="critical"

