"""Authentication router for login/logout operations."""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Header, Request

from ..models.schemas import LoginRequest, LoginResponse, SessionResponse
from ..core.session import session_manager
from ..core.exceptions import SessionError, get_error_message

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    Login and create a new session.

    Credentials are validated against SRT/KTX servers and stored
    temporarily in-memory (encrypted) for the duration of the session.
    Session expires after 30 minutes of inactivity.
    """
    session = await session_manager.create_session(
        rail_type=request.rail_type.value,
        user_id=request.user_id,
        password=request.password,
    )

    return LoginResponse(
        session_id=session.session_id,
        expires_at=session.expires_at,
        rail_type=request.rail_type,
        user_name=session.user_info.get("name"),
        membership_number=session.user_info.get("membership_number"),
    )


@router.post("/logout")
async def logout(x_session_id: Optional[str] = Header(None)):
    """
    End session and clear all credentials.

    All associated jobs will be cancelled and credentials will be
    securely deleted from memory.
    """
    if x_session_id:
        await session_manager.destroy_session(x_session_id)

    return {"message": "Logged out successfully"}


@router.get("/session", response_model=SessionResponse)
async def check_session(x_session_id: Optional[str] = Header(None)):
    """
    Check if the current session is valid.

    Returns session validity and remaining time.
    """
    if not x_session_id:
        return SessionResponse(valid=False)

    session = session_manager.get_session(x_session_id)
    if not session:
        return SessionResponse(valid=False)

    # Refresh session on activity
    session_manager.refresh_session(x_session_id)

    return SessionResponse(
        valid=True,
        expires_at=session.expires_at,
        rail_type=session.rail_type,
    )
