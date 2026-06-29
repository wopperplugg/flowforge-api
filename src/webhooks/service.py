import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from src.common.enums import OrganizationRole
from src.common.exceptions import PermissionDeniedError