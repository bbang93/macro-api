"""WebSocket connection manager for real-time updates."""

from typing import Dict, Set, Any, Optional
from datetime import datetime
import asyncio
import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections for real-time job updates.

    Features:
    - Connection tracking by session ID
    - Broadcast to all connections in a session
    - Automatic cleanup on disconnect
    - Heartbeat/ping support
    """

    def __init__(self):
        # session_id -> set of WebSocket connections
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()

        async with self._lock:
            if session_id not in self._connections:
                self._connections[session_id] = set()
            self._connections[session_id].add(websocket)

        logger.info(f"WebSocket connected for session {session_id[:8]}...")

    async def disconnect(self, websocket: WebSocket, session_id: str) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            if session_id in self._connections:
                self._connections[session_id].discard(websocket)
                if not self._connections[session_id]:
                    del self._connections[session_id]

        logger.info(f"WebSocket disconnected for session {session_id[:8]}...")

    async def broadcast_to_session(
        self,
        session_id: str,
        event_type: str,
        job_id: str,
        data: Dict[str, Any],
    ) -> None:
        """Broadcast an event to all connections in a session."""
        message = {
            "type": event_type,
            "job_id": job_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": data,
        }

        async with self._lock:
            connections = self._connections.get(session_id, set()).copy()

        dead_connections = []
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket: {e}")
                dead_connections.append(websocket)

        # Clean up dead connections
        if dead_connections:
            async with self._lock:
                if session_id in self._connections:
                    for ws in dead_connections:
                        self._connections[session_id].discard(ws)

    async def send_to_connection(
        self,
        websocket: WebSocket,
        event_type: str,
        data: Dict[str, Any],
        job_id: Optional[str] = None,
    ) -> None:
        """Send an event to a specific connection."""
        message = {
            "type": event_type,
            "job_id": job_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": data,
        }
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.warning(f"Failed to send to WebSocket: {e}")

    def get_connection_count(self, session_id: str) -> int:
        """Get the number of active connections for a session."""
        return len(self._connections.get(session_id, set()))

    async def close_session_connections(self, session_id: str, reason: str = "Session ended") -> None:
        """Close all connections for a session."""
        async with self._lock:
            connections = self._connections.pop(session_id, set())

        for websocket in connections:
            try:
                await websocket.close(code=1000, reason=reason)
            except Exception:
                pass


# Event type constants
class EventTypes:
    """WebSocket event type constants."""

    JOB_STARTED = "job_started"
    SEARCH_PROGRESS = "search_progress"
    RESERVE_ATTEMPT = "reserve_attempt"
    RESERVE_SUCCESS = "reserve_success"
    RESERVE_FAILED = "reserve_failed"
    JOB_COMPLETED = "job_completed"
    JOB_CANCELLED = "job_cancelled"
    SESSION_EXPIRED = "session_expired"
    ERROR = "error"
    PONG = "pong"


# Global connection manager instance
connection_manager = ConnectionManager()
