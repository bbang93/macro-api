"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .core.session import session_manager
from .core.websocket import connection_manager, EventTypes
from .core.exceptions import (
    TrainMacroError,
    AuthenticationError,
    SessionError,
    ValidationError,
    RailServiceError,
)
from .routers import auth_router, trains_router, jobs_router, reservations_router, settings_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting Train Macro API...")
    await session_manager.start()
    logger.info("Train Macro API started successfully")

    yield

    # Shutdown
    logger.info("Shutting down Train Macro API...")
    await session_manager.stop()
    logger.info("Train Macro API shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Train Macro API",
    description="REST API for SRT/KTX train booking automation",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["X-Session-ID", "Content-Type"],
)


# Exception handlers
@app.exception_handler(AuthenticationError)
async def authentication_error_handler(request: Request, exc: AuthenticationError):
    """Handle authentication errors."""
    return JSONResponse(
        status_code=401,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(SessionError)
async def session_error_handler(request: Request, exc: SessionError):
    """Handle session errors."""
    return JSONResponse(
        status_code=401,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError):
    """Handle validation errors."""
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(RailServiceError)
async def rail_service_error_handler(request: Request, exc: RailServiceError):
    """Handle rail service errors."""
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(TrainMacroError)
async def train_macro_error_handler(request: Request, exc: TrainMacroError):
    """Handle general train macro errors."""
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


# Include routers
app.include_router(auth_router)
app.include_router(trains_router)
app.include_router(jobs_router)
app.include_router(reservations_router)
app.include_router(settings_router)


# WebSocket endpoint
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time job updates.

    Connect with session_id to receive updates for all jobs in that session.
    """
    # Validate session
    session = session_manager.get_session(session_id)
    if not session:
        await websocket.close(code=4001, reason="Invalid or expired session")
        return

    # Connect
    await connection_manager.connect(websocket, session_id)
    session.websocket_connections.add(websocket)

    try:
        while True:
            # Wait for messages from client
            data = await websocket.receive_json()

            # Handle client messages
            if data.get("type") == "ping":
                await connection_manager.send_to_connection(
                    websocket, EventTypes.PONG, {"timestamp": data.get("timestamp")}
                )
            elif data.get("type") == "cancel_job":
                job_id = data.get("job_id")
                if job_id:
                    from .services.job_service import job_service

                    await job_service.cancel_job(job_id)

            # Refresh session on activity
            session_manager.refresh_session(session_id)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await connection_manager.disconnect(websocket, session_id)
        session.websocket_connections.discard(websocket)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "active_sessions": session_manager.active_session_count,
    }


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": "Train Macro API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }
