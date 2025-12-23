"""API routers."""

from .auth import router as auth_router
from .trains import router as trains_router
from .jobs import router as jobs_router
from .reservations import router as reservations_router
from .settings import router as settings_router

__all__ = [
    "auth_router",
    "trains_router",
    "jobs_router",
    "reservations_router",
    "settings_router",
]
