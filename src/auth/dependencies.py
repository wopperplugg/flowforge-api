import uuid
from typing import Annotated

from fastapi import Depends 
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.auth.tokens import decode_token
from src.common.dependencies import DbSession
from src.common.exceptions import InvalidTokenError
from src.users.models import User
from src.users.repository import UserRepository

bearer_scheme = HTTPBearer(auto_error=False)

async def get_current_user(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
        session: DbSession
) -> User: 
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise InvalidTokenError()
    
    payload = decode_token(credentials.credentials, expected_type="access")
    raw_subject = payload.get("sub")
    try: 
        user_id = uuid.UUID(str(raw_subject))
    except ValueError as exc: 
        raise InvalidTokenError() from exc
    
    user = await UserRepository(session).get_by_id(user_id)
    if user is None or not user.is_active:
        raise InvalidTokenError()
    
    return user