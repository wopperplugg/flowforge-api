import uuid 
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from src.auth.dependencies import get_current_user
from src.auth.schemas import (
    LoginRequest, 
    LogoutResponse,
    RefreshSessionResponse,
    RefreshTokenRequest,
    TokenResponse,
)
from src.auth.service import AuthService 
from src.common.dependencies import DbSession
from src.users.models import User
from src.users.schemas import UserCreate, UserResponse
from src.users.service import UserService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

def get_user_service(
        session: DbSession,
) -> UserService:
    return UserService(session)

def get_auth_service(
        session: DbSession,
) -> AuthService:
    return AuthService(session)

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: UserCreate,
    user_service: Annotated[UserService, Depends(get_user_service)]
) -> UserResponse:
    user = await user_service.create_user(payload)
    return UserResponse.model_validate(user)

@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    payload: LoginRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    return await auth_service.login(
        payload,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )

@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    payload: RefreshTokenRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    return await auth_service.refresh(
        payload,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )

@router.post("/logout", response_model=LogoutResponse)
async def logout(
    payload: RefreshTokenRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> LogoutResponse:
    revoked = await auth_service.logout(payload)
    return LogoutResponse(revoked=revoked)

@router.post("/logout-all", response_model=LogoutResponse)
async def logout_all(
    current_user: Annotated[User, Depends(get_current_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> LogoutResponse:
    revoked = await auth_service.logout_all(current_user)
    return LogoutResponse(revoked=revoked)

@router.get("/sessions", response_model=list[RefreshSessionResponse])
async def list_sesions(
    current_user: Annotated[User, Depends(get_current_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> list[RefreshSessionResponse]:
    sessions = await auth_service.list_sessions(current_user)
    return [RefreshSessionResponse.model_validate(session) for session in sessions]

@router.delete("/sessions/{session_id}", response_model=LogoutResponse)
async def revoke_session(
    session_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> LogoutResponse:
    revoked = await auth_service.revoke_session(current_user, session_id)
    return LogoutResponse(revoked=revoked)

@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    return UserResponse.model_validate(current_user)