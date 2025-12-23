"""Core modules for the API."""

from .exceptions import (
    TrainMacroError,
    AuthenticationError,
    SessionError,
    ValidationError,
    RailServiceError,
    NetFunnelError,
)
from .session import SessionManager, Session
from .security import CredentialHandler
from .websocket import ConnectionManager

__all__ = [
    "TrainMacroError",
    "AuthenticationError",
    "SessionError",
    "ValidationError",
    "RailServiceError",
    "NetFunnelError",
    "SessionManager",
    "Session",
    "CredentialHandler",
    "ConnectionManager",
]
