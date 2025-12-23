"""Job management router for macro booking jobs."""

from typing import List
from fastapi import APIRouter, Header, HTTPException

from ..models.schemas import JobCreateRequest, Job
from ..core.session import session_manager
from ..core.exceptions import TrainMacroError
from ..services.job_service import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=Job, status_code=201)
async def create_job(
    request: JobCreateRequest,
    x_session_id: str = Header(..., description="Session ID from login"),
):
    """
    Start a new booking macro job.

    The job will run in the background, continuously searching for
    available seats on the selected trains. Progress updates are
    sent via WebSocket.
    """
    session = session_manager.require_session(x_session_id)

    # Refresh session on activity
    session_manager.refresh_session(x_session_id)

    job = await job_service.create_job(session, request)
    return job.to_response()


@router.get("", response_model=List[Job])
async def list_jobs(
    x_session_id: str = Header(..., description="Session ID from login"),
):
    """
    List all jobs for the current session.

    Returns jobs in all states (pending, running, completed, failed, cancelled).
    """
    session = session_manager.require_session(x_session_id)

    # Refresh session on activity
    session_manager.refresh_session(x_session_id)

    jobs = job_service.get_session_jobs(session)
    return [job.to_response() for job in jobs]


@router.get("/{job_id}", response_model=Job)
async def get_job(
    job_id: str,
    x_session_id: str = Header(..., description="Session ID from login"),
):
    """
    Get status of a specific job.
    """
    session = session_manager.require_session(x_session_id)

    job = job_service.get_job(job_id)
    if not job or job.session_id != session.session_id:
        raise HTTPException(status_code=404, detail="Job not found")

    return job.to_response()


@router.delete("/{job_id}")
async def cancel_job(
    job_id: str,
    x_session_id: str = Header(..., description="Session ID from login"),
):
    """
    Cancel a running job.

    Already completed or failed jobs cannot be cancelled.
    """
    session = session_manager.require_session(x_session_id)

    job = job_service.get_job(job_id)
    if not job or job.session_id != session.session_id:
        raise HTTPException(status_code=404, detail="Job not found")

    success = await job_service.cancel_job(job_id)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Job cannot be cancelled (already completed or failed)",
        )

    return {"message": "Job cancelled successfully"}
