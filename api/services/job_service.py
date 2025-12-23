"""Job service for managing macro booking jobs."""

import asyncio
import random
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import uuid4
import logging

from ..models.schemas import Job, JobCreateRequest, Reservation, PassengerCount
from ..models.enums import JobStatus, SeatType
from ..core.session import Session, session_manager
from ..core.websocket import connection_manager, EventTypes
from ..core.exceptions import RailServiceError
from .rail_service import RailService

# Import srtgo exceptions for session expiry detection
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from srtgo.srt import SRTLoginError
from srtgo.ktx import NeedToLoginError

logger = logging.getLogger(__name__)


def _get_session_notifier(session_id: str):
    """Get notifier for session (lazy import to avoid circular dependency)."""
    from ..routers.settings import get_notifier
    return get_notifier(session_id)


class JobData:
    """Internal job data with asyncio task."""

    def __init__(
        self,
        id: str,
        session_id: str,
        departure: str,
        arrival: str,
        date: str,
        time: str,
        passengers: PassengerCount,
        seat_type: SeatType,
        selected_trains: List[int],
        prefer_window: bool = False,
        use_standby: bool = False,
        train_types: Optional[List] = None,
    ):
        self.id = id
        self.session_id = session_id
        self.departure = departure
        self.arrival = arrival
        self.date = date
        self.time = time
        self.passengers = passengers
        self.seat_type = seat_type
        self.selected_trains = selected_trains
        self.prefer_window = prefer_window
        self.use_standby = use_standby
        self.train_types = train_types
        self.status = JobStatus.PENDING
        self.attempt_count = 0
        self.created_at = datetime.utcnow()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.task: Optional[asyncio.Task] = None
        self.cancelled = False

    def to_response(self) -> Job:
        """Convert to API response model."""
        return Job(
            id=self.id,
            status=self.status,
            departure=self.departure,
            arrival=self.arrival,
            date=self.date,
            time=self.time,
            passengers=self.passengers,
            seat_type=self.seat_type,
            selected_trains=self.selected_trains,
            prefer_window=self.prefer_window,
            use_standby=self.use_standby,
            train_types=self.train_types,
            attempt_count=self.attempt_count,
            created_at=self.created_at,
            started_at=self.started_at,
            completed_at=self.completed_at,
            result=Reservation(**self.result) if self.result else None,
            error=self.error,
        )


class JobService:
    """
    Manages macro booking jobs with background execution.

    Features:
    - Async job execution with cancellation support
    - Real-time WebSocket updates
    - Automatic retry with backoff
    - Session-based job isolation
    """

    def __init__(self):
        self._jobs: Dict[str, JobData] = {}
        self._lock = asyncio.Lock()

    async def create_job(
        self,
        session: Session,
        request: JobCreateRequest,
    ) -> JobData:
        """Create and start a new booking job."""
        job_id = str(uuid4())

        job = JobData(
            id=job_id,
            session_id=session.session_id,
            departure=request.departure,
            arrival=request.arrival,
            date=request.date,
            time=request.time,
            passengers=request.passengers,
            seat_type=request.seat_type,
            selected_trains=request.selected_trains,
            prefer_window=request.prefer_window,
            use_standby=request.use_standby,
            train_types=request.train_types,
        )

        async with self._lock:
            self._jobs[job_id] = job
            session.jobs[job_id] = job

        # Start the booking loop
        job.task = asyncio.create_task(self._run_booking_loop(job, session))

        logger.info(f"Created job {job_id[:8]}... for session {session.session_id[:8]}...")
        return job

    def get_job(self, job_id: str) -> Optional[JobData]:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def get_session_jobs(self, session: Session) -> List[JobData]:
        """Get all jobs for a session."""
        return list(session.jobs.values())

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job."""
        job = self._jobs.get(job_id)
        if not job:
            return False

        if job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
            return False

        job.cancelled = True
        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.utcnow()

        if job.task and not job.task.done():
            job.task.cancel()

        # Broadcast cancellation
        await connection_manager.broadcast_to_session(
            job.session_id,
            EventTypes.JOB_CANCELLED,
            job.id,
            {"status": "cancelled"},
        )

        logger.info(f"Cancelled job {job_id[:8]}...")
        return True

    async def _relogin_if_needed(self, session: Session) -> bool:
        """
        Attempt to relogin if session is expired.

        Returns:
            True if relogin was successful, False otherwise
        """
        try:
            # Get stored credentials
            user_id, password = session_manager.get_credentials(session)

            # Attempt relogin
            logger.info(f"Attempting auto-relogin for session {session.session_id[:8]}...")
            rail_client, user_info = await RailService.login(
                session.rail_type, user_id, password
            )

            # Update session with new client
            session.rail_client = rail_client
            session.user_info = user_info

            logger.info(f"Auto-relogin successful for session {session.session_id[:8]}...")
            return True

        except Exception as e:
            logger.error(f"Auto-relogin failed for session {session.session_id[:8]}...: {e}")
            return False

    async def _run_booking_loop(self, job: JobData, session: Session) -> None:
        """
        Main booking loop that searches and attempts reservation.

        Uses gamma distribution for retry intervals (avg 1.25s)
        to avoid rate limiting while staying responsive.
        """
        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()

        # Broadcast job started
        await connection_manager.broadcast_to_session(
            session.session_id,
            EventTypes.JOB_STARTED,
            job.id,
            {
                "departure": job.departure,
                "arrival": job.arrival,
                "date": job.date,
                "selected_train_count": len(job.selected_trains),
            },
        )

        rail_service = RailService.create(session.rail_type, session.rail_client)

        # Set NetFunnel callback to broadcast waiting status
        def netfunnel_callback(status: str, nwait: int):
            """Callback for NetFunnel waiting status."""
            asyncio.create_task(
                connection_manager.broadcast_to_session(
                    session.session_id,
                    EventTypes.NETFUNNEL_WAITING if status == "waiting" else EventTypes.NETFUNNEL_PASSED,
                    job.id,
                    {
                        "status": status,
                        "wait_count": nwait,
                        "message": f"NetFunnel 대기중... ({nwait}명)" if status == "waiting" else "NetFunnel 통과"
                    },
                )
            )

        rail_service.set_netfunnel_callback(netfunnel_callback)

        try:
            while not job.cancelled:
                job.attempt_count += 1

                try:
                    # Search for trains (with auto-relogin on session expiry)
                    try:
                        trains = await rail_service.search_trains(
                            departure=job.departure,
                            arrival=job.arrival,
                            date=job.date,
                            time=job.time,
                            passengers=job.passengers,
                        )
                    except (SRTLoginError, NeedToLoginError) as e:
                        # Session expired, attempt auto-relogin
                        logger.warning(f"Session expired for job {job.id[:8]}..., attempting relogin: {e}")

                        if await self._relogin_if_needed(session):
                            # Relogin successful, update rail_service and retry
                            rail_service = RailService.create(session.rail_type, session.rail_client)
                            rail_service.set_netfunnel_callback(netfunnel_callback)

                            # Retry search
                            trains = await rail_service.search_trains(
                                departure=job.departure,
                                arrival=job.arrival,
                                date=job.date,
                                time=job.time,
                                passengers=job.passengers,
                            )
                        else:
                            # Relogin failed
                            raise RailServiceError(
                                "SESSION_EXPIRED",
                                "세션이 만료되어 재로그인에 실패했습니다.",
                            )

                    # Check selected trains for availability
                    available_seats = []
                    for idx in job.selected_trains:
                        if idx < len(trains):
                            train = trains[idx]
                            available_seats.append({
                                "train_index": idx,
                                "general": train["general_seat_available"],
                                "special": train["special_seat_available"],
                                "standby": train["standby_available"],
                            })

                    # Count available seats
                    available_count = sum(
                        1 for s in available_seats
                        if s["general"] or s["special"] or s["standby"]
                    )

                    # Create log message
                    if available_count > 0:
                        message = f"좌석 발견! {available_count}개 열차 예매 시도 중..."
                    else:
                        message = f"조회 #{job.attempt_count}: 빈 좌석 없음, 재조회..."

                    # Broadcast search progress
                    await connection_manager.broadcast_to_session(
                        session.session_id,
                        EventTypes.SEARCH_PROGRESS,
                        job.id,
                        {
                            "attempt_count": job.attempt_count,
                            "elapsed_seconds": (datetime.utcnow() - job.started_at).total_seconds(),
                            "found_trains": len(trains),
                            "available_seats": available_seats,
                            "available_count": available_count,
                            "message": message,
                        },
                    )

                    logger.debug(f"Job {job.id[:8]}: {message}")

                    # Try to reserve each selected train
                    for idx in job.selected_trains:
                        if job.cancelled:
                            break

                        if idx >= len(trains):
                            continue

                        train = trains[idx]

                        # Check if seat is available based on preference
                        can_reserve = False
                        can_standby = False

                        if job.seat_type in (SeatType.GENERAL_FIRST, SeatType.GENERAL_ONLY):
                            can_reserve = train["general_seat_available"]
                        if not can_reserve and job.seat_type in (SeatType.SPECIAL_FIRST, SeatType.SPECIAL_ONLY):
                            can_reserve = train["special_seat_available"]
                        if not can_reserve and job.seat_type == SeatType.GENERAL_FIRST:
                            can_reserve = train["special_seat_available"]
                        if not can_reserve and job.seat_type == SeatType.SPECIAL_FIRST:
                            can_reserve = train["general_seat_available"]

                        # Check for standby availability if no regular seats and standby is enabled
                        if not can_reserve and job.use_standby:
                            can_standby = train["standby_available"]

                        if not can_reserve and not can_standby:
                            continue

                        # Determine reservation type
                        is_standby = not can_reserve and can_standby
                        seat_type_str = "standby" if is_standby else (
                            "general" if train["general_seat_available"] else "special"
                        )

                        # Broadcast reservation attempt
                        await connection_manager.broadcast_to_session(
                            session.session_id,
                            EventTypes.RESERVE_ATTEMPT,
                            job.id,
                            {
                                "train_index": idx,
                                "train_name": train["train_name"],
                                "train_number": train["train_number"],
                                "dep_time": train["dep_time"],
                                "seat_type": seat_type_str,
                                "is_standby": is_standby,
                            },
                        )

                        try:
                            # Attempt reservation (with auto-relogin on session expiry)
                            try:
                                if is_standby:
                                    # Attempt standby reservation
                                    reservation = await rail_service.reserve_standby(
                                        train_index=idx,
                                        passengers=job.passengers,
                                        seat_type=job.seat_type,
                                    )
                                else:
                                    # Regular reservation
                                    reservation = await rail_service.reserve(
                                        train_index=idx,
                                        passengers=job.passengers,
                                        seat_type=job.seat_type,
                                        prefer_window=job.prefer_window,
                                    )
                            except (SRTLoginError, NeedToLoginError) as e:
                                # Session expired during reservation, attempt auto-relogin
                                logger.warning(f"Session expired during reservation for job {job.id[:8]}...: {e}")

                                if await self._relogin_if_needed(session):
                                    # Relogin successful, update rail_service and retry reservation
                                    rail_service = RailService.create(session.rail_type, session.rail_client)
                                    rail_service.set_netfunnel_callback(netfunnel_callback)

                                    # Retry reservation
                                    if is_standby:
                                        reservation = await rail_service.reserve_standby(
                                            train_index=idx,
                                            passengers=job.passengers,
                                            seat_type=job.seat_type,
                                        )
                                    else:
                                        reservation = await rail_service.reserve(
                                            train_index=idx,
                                            passengers=job.passengers,
                                            seat_type=job.seat_type,
                                            prefer_window=job.prefer_window,
                                        )
                                else:
                                    # Relogin failed
                                    raise RailServiceError(
                                        "SESSION_EXPIRED",
                                        "세션이 만료되어 재로그인에 실패했습니다.",
                                    )

                            # Success!
                            job.status = JobStatus.SUCCESS
                            job.completed_at = datetime.utcnow()
                            job.result = reservation

                            await connection_manager.broadcast_to_session(
                                session.session_id,
                                EventTypes.RESERVE_SUCCESS,
                                job.id,
                                reservation,
                            )

                            await connection_manager.broadcast_to_session(
                                session.session_id,
                                EventTypes.JOB_COMPLETED,
                                job.id,
                                {
                                    "status": "success",
                                    "total_attempts": job.attempt_count,
                                    "elapsed_seconds": (job.completed_at - job.started_at).total_seconds(),
                                    "reservation": reservation,
                                    "is_standby": is_standby,
                                },
                            )

                            logger.info(
                                f"Job {job.id[:8]}... succeeded after {job.attempt_count} attempts"
                                f" ({'standby' if is_standby else 'regular'})"
                            )

                            # Send Telegram notification
                            try:
                                notifier = _get_session_notifier(session.session_id)
                                if notifier.enabled:
                                    await notifier.send_reservation_success(
                                        reservation, is_standby=is_standby
                                    )
                            except Exception as notify_err:
                                logger.warning(f"Failed to send Telegram notification: {notify_err}")

                            return

                        except RailServiceError as e:
                            # Broadcast reservation failure
                            await connection_manager.broadcast_to_session(
                                session.session_id,
                                EventTypes.RESERVE_FAILED,
                                job.id,
                                {
                                    "train_index": idx,
                                    "error_code": e.code,
                                    "error_message": e.message,
                                    "retryable": e.code in ("RESERVE_SOLD_OUT", "STANDBY_NOT_AVAILABLE"),
                                    "is_standby": is_standby,
                                },
                            )

                            if e.code not in ("RESERVE_SOLD_OUT", "STANDBY_NOT_AVAILABLE"):
                                # Non-retryable error
                                raise

                except RailServiceError as e:
                    if e.code not in ("RESERVE_SOLD_OUT", "TRAIN_SEARCH_NO_RESULTS"):
                        # Fatal error
                        job.status = JobStatus.FAILED
                        job.completed_at = datetime.utcnow()
                        job.error = e.message

                        await connection_manager.broadcast_to_session(
                            session.session_id,
                            EventTypes.JOB_COMPLETED,
                            job.id,
                            {
                                "status": "failed",
                                "total_attempts": job.attempt_count,
                                "elapsed_seconds": (job.completed_at - job.started_at).total_seconds(),
                                "final_error": e.message,
                            },
                        )

                        logger.error(f"Job {job.id[:8]}... failed: {e.message}")

                        # Send Telegram notification for failure
                        try:
                            notifier = _get_session_notifier(session.session_id)
                            if notifier.enabled:
                                await notifier.send_job_failed(
                                    departure=job.departure,
                                    arrival=job.arrival,
                                    error_message=e.message,
                                    attempt_count=job.attempt_count,
                                )
                        except Exception as notify_err:
                            logger.warning(f"Failed to send Telegram notification: {notify_err}")

                        return

                # Wait before next attempt (gamma distribution: avg 1.25s)
                wait_time = max(0.25, random.gammavariate(4, 0.25))
                await asyncio.sleep(wait_time)

        except asyncio.CancelledError:
            if not job.cancelled:
                job.status = JobStatus.CANCELLED
                job.completed_at = datetime.utcnow()
            logger.info(f"Job {job.id[:8]}... was cancelled")

        except Exception as e:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.utcnow()
            job.error = str(e)

            await connection_manager.broadcast_to_session(
                session.session_id,
                EventTypes.JOB_COMPLETED,
                job.id,
                {
                    "status": "failed",
                    "total_attempts": job.attempt_count,
                    "elapsed_seconds": (job.completed_at - job.started_at).total_seconds()
                    if job.started_at
                    else 0,
                    "final_error": str(e),
                },
            )

            logger.exception(f"Job {job.id[:8]}... failed with exception")


# Global job service instance
job_service = JobService()
