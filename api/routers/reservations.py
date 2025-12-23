"""Reservation management router."""

from typing import List
from fastapi import APIRouter, Header, HTTPException

from ..models.schemas import Reservation, PaymentRequest, PaymentResponse
from ..core.session import session_manager
from ..services.rail_service import RailService

router = APIRouter(prefix="/reservations", tags=["reservations"])


@router.get("", response_model=List[Reservation])
async def list_reservations(
    x_session_id: str = Header(..., description="Session ID from login"),
):
    """
    Get user's current reservations.

    Returns all reservations including paid and unpaid.
    """
    session = session_manager.require_session(x_session_id)

    # Refresh session on activity
    session_manager.refresh_session(x_session_id)

    rail_service = RailService.create(session.rail_type, session.rail_client)
    reservations = await rail_service.get_reservations()

    return [Reservation(**r) for r in reservations]


@router.post("/{reservation_id}/cancel")
async def cancel_reservation(
    reservation_id: str,
    x_session_id: str = Header(..., description="Session ID from login"),
):
    """
    Cancel a reservation.

    Only unpaid reservations can be cancelled through this API.
    """
    session = session_manager.require_session(x_session_id)

    # Refresh session on activity
    session_manager.refresh_session(x_session_id)

    rail_service = RailService.create(session.rail_type, session.rail_client)
    success = await rail_service.cancel_reservation(reservation_id)

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Failed to cancel reservation",
        )

    return {"message": "Reservation cancelled successfully"}


@router.post("/{reservation_id}/pay", response_model=PaymentResponse)
async def pay_reservation(
    reservation_id: str,
    payment: PaymentRequest,
    x_session_id: str = Header(..., description="Session ID from login"),
):
    """
    Pay for a reservation with credit card.

    Payment must be made before the payment deadline.
    Only unpaid reservations can be paid.

    Args:
        reservation_id: Reservation number to pay
        payment: Credit card payment details

    Returns:
        Payment result with success status and details
    """
    session = session_manager.require_session(x_session_id)

    # Refresh session on activity
    session_manager.refresh_session(x_session_id)

    rail_service = RailService.create(session.rail_type, session.rail_client)

    try:
        result = await rail_service.pay_with_card(
            reservation_number=reservation_id,
            card_number=payment.card_number,
            card_password=payment.card_password,
            birth_or_business=payment.birth_or_business,
            expire_date=payment.expire_date,
            installment=payment.installment,
            card_type=payment.card_type,
        )
        return PaymentResponse(**result)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )
