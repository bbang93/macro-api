"""Session management for temporary credential storage."""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Set, TYPE_CHECKING
from uuid import uuid4
import asyncio
import logging

from .security import CredentialHandler
from .exceptions import AuthenticationError, SessionError, get_error_message

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = logging.getLogger(__name__)


class Session:
    """Represents a user session with encrypted credentials."""

    def __init__(
        self,
        session_id: str,
        rail_type: str,
        encrypted_credentials: bytes,
        user_info: Dict[str, Any],
        expires_at: datetime,
    ):
        self.session_id = session_id
        self.rail_type = rail_type
        self.encrypted_credentials = encrypted_credentials
        self.user_info = user_info
        self.expires_at = expires_at
        self.rail_client: Optional[Any] = None  # Cached login instance
        self.jobs: Dict[str, Any] = {}
        self.websocket_connections: Set["WebSocket"] = set()
        self._cleanup_task: Optional[asyncio.Task] = None

    @property
    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.now(timezone.utc) > self.expires_at


class SessionManager:
    """
    Manages user sessions with in-memory credential storage.

    Features:
    - Encrypted credentials (Fernet)
    - Automatic TTL-based cleanup
    - WebSocket connection tracking
    - Job lifecycle management
    """

    def __init__(self, ttl_minutes: int = 30):
        self.ttl_minutes = ttl_minutes
        self._sessions: Dict[str, Session] = {}
        self._credential_handler = CredentialHandler()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the session manager background tasks."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("Session cleanup task started")

    async def stop(self) -> None:
        """Stop the session manager and cleanup all sessions."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        # Cleanup all sessions
        for session_id in list(self._sessions.keys()):
            await self.destroy_session(session_id)

        logger.info("Session manager stopped")

    async def _cleanup_loop(self) -> None:
        """Background task to clean expired sessions."""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")

    async def _cleanup_expired(self) -> None:
        """Remove all expired sessions."""
        async with self._lock:
            now = datetime.now(timezone.utc)
            expired = [
                sid for sid, session in self._sessions.items() if session.is_expired
            ]
            for sid in expired:
                await self._destroy_session_internal(sid)
                logger.info(f"Cleaned up expired session: {sid[:8]}...")

    async def create_session(
        self,
        rail_type: str,
        user_id: str,
        password: str,
    ) -> Session:
        """
        Validate credentials and create a new session.

        Args:
            rail_type: "SRT" or "KTX"
            user_id: User's membership number, email, or phone
            password: User's password

        Returns:
            Created Session object

        Raises:
            AuthenticationError: If credentials are invalid
        """
        from ..services.rail_service import RailService

        # Validate by actually logging in
        try:
            rail_client, user_info = await RailService.login(
                rail_type, user_id, password
            )
        except Exception as e:
            error_msg = str(e)
            if "비밀번호" in error_msg or "회원" in error_msg:
                raise AuthenticationError(
                    "AUTH_INVALID_CREDENTIALS",
                    get_error_message("AUTH_INVALID_CREDENTIALS"),
                )
            elif "IP" in error_msg.upper() or "차단" in error_msg:
                raise AuthenticationError(
                    "AUTH_IP_BLOCKED",
                    get_error_message("AUTH_IP_BLOCKED"),
                )
            else:
                raise AuthenticationError(
                    "AUTH_INVALID_CREDENTIALS",
                    get_error_message("AUTH_INVALID_CREDENTIALS"),
                    {"original_error": error_msg},
                )

        # Encrypt credentials
        encrypted = self._credential_handler.encrypt(user_id, password)

        session_id = str(uuid4())
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=self.ttl_minutes)

        session = Session(
            session_id=session_id,
            rail_type=rail_type,
            encrypted_credentials=encrypted,
            user_info=user_info,
            expires_at=expires_at,
        )
        session.rail_client = rail_client

        async with self._lock:
            self._sessions[session_id] = session

        logger.info(
            f"Created session {session_id[:8]}... for {rail_type} user {user_info.get('name', 'unknown')}"
        )
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get a valid session by ID."""
        session = self._sessions.get(session_id)
        if session and not session.is_expired:
            return session
        return None

    def require_session(self, session_id: Optional[str]) -> Session:
        """Get a session or raise an error if invalid."""
        if not session_id:
            raise SessionError("SESSION_MISSING", get_error_message("SESSION_MISSING"))

        session = self.get_session(session_id)
        if not session:
            raise SessionError("SESSION_EXPIRED", get_error_message("SESSION_EXPIRED"))

        return session

    async def destroy_session(self, session_id: str) -> bool:
        """Destroy a session and cleanup all associated resources."""
        async with self._lock:
            return await self._destroy_session_internal(session_id)

    async def _destroy_session_internal(self, session_id: str) -> bool:
        """Internal session destruction (must be called with lock held)."""
        session = self._sessions.pop(session_id, None)
        if not session:
            return False

        # Cancel all running jobs
        for job in session.jobs.values():
            if hasattr(job, "task") and job.task and not job.task.done():
                job.task.cancel()

        # Close all websocket connections
        for ws in list(session.websocket_connections):
            try:
                await ws.close(code=1000, reason="Session ended")
            except Exception:
                pass

        # Logout from rail service
        if session.rail_client:
            try:
                if hasattr(session.rail_client, "logout"):
                    session.rail_client.logout()
            except Exception:
                pass

        logger.info(f"Destroyed session {session_id[:8]}...")
        return True

    def refresh_session(self, session_id: str) -> bool:
        """Extend session TTL on activity."""
        session = self._sessions.get(session_id)
        if session and not session.is_expired:
            session.expires_at = datetime.now(timezone.utc) + timedelta(minutes=self.ttl_minutes)
            return True
        return False

    def get_credentials(self, session: Session) -> tuple[str, str]:
        """Decrypt and return credentials for a session."""
        return self._credential_handler.decrypt(session.encrypted_credentials)

    @property
    def active_session_count(self) -> int:
        """Get count of active (non-expired) sessions."""
        now = datetime.now(timezone.utc)
        return sum(1 for s in self._sessions.values() if s.expires_at > now)


# Global session manager instance
session_manager = SessionManager()
