"""Train search and station listing router."""

from typing import List
from fastapi import APIRouter, Header, Query

from ..models.schemas import TrainSearchRequest, Train, StationsResponse
from ..models.enums import RailType
from ..core.session import session_manager
from ..services.rail_service import RailService

router = APIRouter(tags=["trains"])


@router.get("/stations", response_model=StationsResponse)
async def get_stations(rail_type: RailType = Query(..., description="SRT 또는 KTX")):
    """
    Get available stations for the specified rail type.

    No authentication required.
    """
    stations = RailService.get_stations(rail_type)
    return StationsResponse(rail_type=rail_type, stations=stations)


@router.post("/trains/search", response_model=List[Train])
async def search_trains(
    request: TrainSearchRequest,
    x_session_id: str = Header(..., description="Session ID from login"),
):
    """
    Search for available trains.

    Requires authenticated session. Results are cached for subsequent
    reservation attempts within the same session.
    """
    session = session_manager.require_session(x_session_id)

    # Refresh session on activity
    session_manager.refresh_session(x_session_id)

    rail_service = RailService.create(session.rail_type, session.rail_client)

    trains = await rail_service.search_trains(
        departure=request.departure,
        arrival=request.arrival,
        date=request.date,
        time=request.time,
        passengers=request.passengers,
        train_types=request.train_types,
    )

    return [Train(**t) for t in trains]
