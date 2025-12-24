"""Rail service wrapper for SRT and KTX operations."""

import asyncio
from functools import partial
from typing import List, Dict, Any, Tuple, Union, Optional, TYPE_CHECKING
import logging

# Import existing SRT/KTX modules
import sys
import os

# Add parent directory to path for srtgo imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from srtgo.srt import (
    SRT,
    SRTTrain,
    SRTReservation,
    Adult as SRTAdult,
    Child as SRTChild,
    Senior as SRTSenior,
    Disability1To3 as SRTDisability1To3,
    Disability4To6 as SRTDisability4To6,
    SeatType as SRTSeatType,
    STATION_CODE as SRT_STATIONS,
    WINDOW_SEAT as SRT_WINDOW_SEAT,
)
from srtgo.ktx import (
    Korail,
    Train as KTXTrain,
    Reservation as KTXReservation,
    AdultPassenger,
    ChildPassenger,
    SeniorPassenger,
    Disability1To3Passenger,
    Disability4To6Passenger,
    ToddlerPassenger,
    ReserveOption,
    TrainType as KTXTrainType,
)

from ..models.enums import RailType, SeatType, PassengerType, TrainType
from ..models.schemas import PassengerCount
from ..core.exceptions import RailServiceError, get_error_message

logger = logging.getLogger(__name__)

# Mapping from macro-api TrainType enum to ktx TrainType class values
# 기존 srtgo 방식: train_type을 API 파라미터로 직접 전달
TRAIN_TYPE_TO_KTX = {
    TrainType.KTX: KTXTrainType.KTX,
    TrainType.KTX_SANCHEON: KTXTrainType.KTX_SANCHEON,
    TrainType.ITX_SAEMAEUL: KTXTrainType.ITX_SAEMAEUL,
    TrainType.ITX_CHEONGCHUN: KTXTrainType.ITX_CHEONGCHUN,
    TrainType.MUGUNGHWA: KTXTrainType.MUGUNGHWA,
    TrainType.SAEMAEUL: KTXTrainType.SAEMAEUL,
    TrainType.NURIRO: KTXTrainType.NURIRO,
    TrainType.TONGGEUN: KTXTrainType.TONGGUEN,
    TrainType.AIRPORT: KTXTrainType.AIRPORT,
}

# KTX station list (from srtgo.py)
KTX_STATIONS = [
    "서울",
    "용산",
    "영등포",
    "광명",
    "수원",
    "천안아산",
    "오송",
    "대전",
    "서대전",
    "김천구미",
    "동대구",
    "경주",
    "포항",
    "밀양",
    "구포",
    "부산",
    "울산(통도사)",
    "마산",
    "창원중앙",
    "경산",
    "논산",
    "익산",
    "정읍",
    "광주송정",
    "목포",
    "전주",
    "순천",
    "여수EXPO",
    "청량리",
    "강릉",
    "행신",
    "정동진",
]


class RailService:
    """
    Unified service wrapper for SRT and KTX operations.

    Provides async wrappers around the synchronous SRT/KTX libraries
    with normalized response formats.
    """

    def __init__(self, rail_type: RailType, client: Union[SRT, Korail]):
        self.rail_type = rail_type
        self.client = client
        self._is_srt = rail_type == RailType.SRT
        self._last_trains: List[Any] = []  # Cache for reservation

    def set_netfunnel_callback(self, callback):
        """Set NetFunnel wait callback for SRT (KTX doesn't use NetFunnel)."""
        if self._is_srt and hasattr(self.client, '_netfunnel'):
            self.client._netfunnel.on_wait_callback = callback

    def _build_search_passenger_list(self, passengers: PassengerCount) -> List[Any]:
        """
        Build passenger list for SEARCH operations (srtgo 호환).

        기존 srtgo 방식: 검색 시 모든 승객을 성인으로 통합하여 전달.
        이렇게 하면 검색 결과가 더 안정적으로 반환됨.
        """
        total_count = passengers.total
        if total_count <= 0:
            total_count = 1

        if self._is_srt:
            return [SRTAdult(total_count)]
        else:
            return [AdultPassenger(total_count)]

    def _build_reserve_passenger_list(self, passengers: PassengerCount) -> List[Any]:
        """
        Build passenger list for RESERVE operations (실제 구성 전달).

        예약 시에는 실제 승객 구성을 전달하여 할인이 적용되도록 함.
        """
        passenger_list = []

        if self._is_srt:
            # SRT passengers (no toddler type)
            if passengers.adult > 0:
                passenger_list.append(SRTAdult(passengers.adult))
            if passengers.child > 0:
                passenger_list.append(SRTChild(passengers.child))
            if passengers.senior > 0:
                passenger_list.append(SRTSenior(passengers.senior))
            if passengers.disability_1_3 > 0:
                passenger_list.append(SRTDisability1To3(passengers.disability_1_3))
            if passengers.disability_4_6 > 0:
                passenger_list.append(SRTDisability4To6(passengers.disability_4_6))
        else:
            # KTX passengers (includes toddler)
            if passengers.adult > 0:
                passenger_list.append(AdultPassenger(passengers.adult))
            if passengers.child > 0:
                passenger_list.append(ChildPassenger(passengers.child))
            if passengers.senior > 0:
                passenger_list.append(SeniorPassenger(passengers.senior))
            if passengers.disability_1_3 > 0:
                passenger_list.append(Disability1To3Passenger(passengers.disability_1_3))
            if passengers.disability_4_6 > 0:
                passenger_list.append(Disability4To6Passenger(passengers.disability_4_6))
            if passengers.toddler > 0:
                passenger_list.append(ToddlerPassenger(passengers.toddler))

        # Ensure at least one adult if no passengers specified
        if not passenger_list:
            passenger_list = [SRTAdult(1)] if self._is_srt else [AdultPassenger(1)]

        return passenger_list

    @classmethod
    async def login(
        cls,
        rail_type: Union[RailType, str],
        user_id: str,
        password: str,
    ) -> Tuple[Union[SRT, Korail], Dict[str, Any]]:
        """
        Login to rail service and return client with user info.

        Args:
            rail_type: "SRT" or "KTX"
            user_id: User's ID
            password: User's password

        Returns:
            Tuple of (rail_client, user_info_dict)
        """
        loop = asyncio.get_running_loop()
        rail_type_str = rail_type.value if isinstance(rail_type, RailType) else rail_type

        if rail_type_str == "SRT":
            client = await loop.run_in_executor(
                None, partial(SRT, user_id, password, auto_login=True, verbose=False)
            )
            user_info = {
                "name": getattr(client, "user_name", None),
                "membership_number": getattr(client, "membership_number", user_id),
            }
        else:
            client = await loop.run_in_executor(
                None, partial(Korail, user_id, password, auto_login=True)
            )
            user_info = {
                "name": getattr(client, "name", None),
                "membership_number": getattr(client, "membership_number", user_id),
            }

        logger.info(f"Logged in to {rail_type_str}: {user_info.get('name', 'unknown')}")
        return client, user_info

    @classmethod
    def create(cls, rail_type: RailType, client: Union[SRT, Korail]) -> "RailService":
        """Create a RailService instance from an existing client."""
        return cls(rail_type, client)

    @staticmethod
    def get_stations(rail_type: Union[RailType, str]) -> List[str]:
        """Get available stations for the rail type."""
        rail_type_str = rail_type.value if isinstance(rail_type, RailType) else rail_type
        if rail_type_str == "SRT":
            return list(SRT_STATIONS.keys())
        return KTX_STATIONS

    async def search_trains(
        self,
        departure: str,
        arrival: str,
        date: str,
        time: str = "000000",
        passengers: Optional[PassengerCount] = None,
        train_types: Optional[List[TrainType]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search for available trains.

        Args:
            departure: Departure station name
            arrival: Arrival station name
            date: Date in YYYYMMDD format
            time: Time in HHMMSS format
            passengers: Passenger count by type
            train_types: Train types to filter (KTX only)

        Returns:
            List of normalized train dictionaries
        """
        loop = asyncio.get_running_loop()

        # Build passenger list for SEARCH (성인만 통합 - srtgo 호환)
        if passengers is None:
            passengers = PassengerCount()
        passenger_list = self._build_search_passenger_list(passengers)

        logger.debug(f"Search passengers: {passengers.total}명 (성인으로 통합)")

        try:
            if self._is_srt:
                trains = await loop.run_in_executor(
                    None,
                    partial(
                        self.client.search_train,
                        dep=departure,
                        arr=arrival,
                        date=date,
                        time=time,
                        passengers=passenger_list,
                        available_only=False,
                    ),
                )
            else:
                # KTX: train_type을 API 파라미터로 직접 전달 (기존 srtgo 방식)
                # 여러 train_type이 지정된 경우 첫 번째 것만 사용 (API 제약)
                ktx_train_type = KTXTrainType.ALL
                if train_types and len(train_types) > 0:
                    first_type = train_types[0]
                    ktx_train_type = TRAIN_TYPE_TO_KTX.get(first_type, KTXTrainType.ALL)
                    logger.debug(f"KTX search with train_type: {first_type.value} -> {ktx_train_type}")

                trains = await loop.run_in_executor(
                    None,
                    partial(
                        self.client.search_train,
                        dep=departure,
                        arr=arrival,
                        date=date,
                        time=time,
                        passengers=passenger_list,
                        train_type=ktx_train_type,
                        include_no_seats=True,
                    ),
                )

            # Cache trains for later reservation
            self._last_trains = trains

            # Normalize trains
            normalized_trains = [self._normalize_train(t, i) for i, t in enumerate(trains)]

            # Note: train_type 필터링은 이제 API에서 직접 처리되므로 후처리 불필요

            return normalized_trains

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Train search failed: {error_msg}")

            if "역" in error_msg:
                raise RailServiceError(
                    "TRAIN_SEARCH_INVALID_STATION",
                    get_error_message("TRAIN_SEARCH_INVALID_STATION"),
                )
            raise RailServiceError(
                "TRAIN_SEARCH_NO_RESULTS",
                get_error_message("TRAIN_SEARCH_NO_RESULTS"),
                {"original_error": error_msg},
            )

    def _normalize_train(
        self, train: Union[SRTTrain, KTXTrain], index: int
    ) -> Dict[str, Any]:
        """Convert train object to unified format."""
        if self._is_srt:
            return {
                "index": index,
                "train_code": train.train_code,
                "train_name": train.train_name,
                "train_number": train.train_number,
                "dep_station": train.dep_station_name,
                "arr_station": train.arr_station_name,
                "dep_date": train.dep_date,
                "dep_time": train.dep_time,
                "arr_time": train.arr_time,
                "general_seat_available": train.general_seat_available(),
                "special_seat_available": train.special_seat_available(),
                "standby_available": train.reserve_standby_available(),
                "duration_minutes": self._calc_duration(train.dep_time, train.arr_time),
            }
        else:
            return {
                "index": index,
                "train_code": train.train_type,
                "train_name": train.train_type_name,
                "train_number": train.train_no,
                "dep_station": train.dep_name,
                "arr_station": train.arr_name,
                "dep_date": train.dep_date,
                "dep_time": train.dep_time,
                "arr_time": train.arr_time,
                "general_seat_available": train.has_general_seat(),
                "special_seat_available": train.has_special_seat(),
                "standby_available": train.has_waiting_list(),
                "duration_minutes": self._calc_duration(train.dep_time, train.arr_time),
            }

    async def reserve(
        self,
        train_index: int,
        passengers: Optional[PassengerCount] = None,
        seat_type: SeatType = SeatType.GENERAL_FIRST,
        prefer_window: bool = False,
    ) -> Dict[str, Any]:
        """
        Reserve a train seat.

        Args:
            train_index: Index of train from search results
            passengers: Passenger count by type
            seat_type: Seat preference
            prefer_window: Prefer window seat (SRT only)

        Returns:
            Normalized reservation dictionary
        """
        if train_index >= len(self._last_trains):
            raise RailServiceError(
                "TRAIN_NOT_FOUND",
                "열차를 찾을 수 없습니다. 다시 검색해주세요.",
            )

        train = self._last_trains[train_index]
        loop = asyncio.get_running_loop()

        # Build passenger list for RESERVE (실제 구성 전달 - 할인 적용)
        if passengers is None:
            passengers = PassengerCount()
        passenger_list = self._build_reserve_passenger_list(passengers)

        logger.debug(f"Reserve passengers: {passengers}")

        try:
            if self._is_srt:
                option = getattr(SRTSeatType, seat_type.value)

                # SRT supports window seat preference
                reserve_kwargs = {
                    "train": train,
                    "passengers": passenger_list,
                    "option": option,
                }
                if prefer_window:
                    reserve_kwargs["window_seat"] = True

                reservation = await loop.run_in_executor(
                    None,
                    partial(self.client.reserve, **reserve_kwargs),
                )
            else:
                option = getattr(ReserveOption, seat_type.value)

                reservation = await loop.run_in_executor(
                    None,
                    partial(
                        self.client.reserve,
                        train=train,
                        passengers=passenger_list,
                        option=option,
                    ),
                )

            return self._normalize_reservation(reservation)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Reservation failed: {error_msg}")

            if "매진" in error_msg or "잔여석" in error_msg:
                raise RailServiceError(
                    "RESERVE_SOLD_OUT",
                    get_error_message("RESERVE_SOLD_OUT"),
                )
            elif "중복" in error_msg or "이미" in error_msg:
                raise RailServiceError(
                    "RESERVE_DUPLICATE",
                    get_error_message("RESERVE_DUPLICATE"),
                )
            raise RailServiceError(
                "RESERVE_FAILED",
                get_error_message("RESERVE_FAILED"),
                {"original_error": error_msg},
            )

    async def reserve_standby(
        self,
        train_index: int,
        passengers: Optional[PassengerCount] = None,
        seat_type: SeatType = SeatType.GENERAL_FIRST,
        phone_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Request waitlist reservation for a train.

        Args:
            train_index: Index of train from search results
            passengers: Passenger count by type
            seat_type: Seat preference (will be converted to ONLY type)
            phone_number: Phone number for SMS notifications (SRT only)

        Returns:
            Normalized reservation dictionary with is_waiting=True
        """
        if train_index >= len(self._last_trains):
            raise RailServiceError(
                "TRAIN_NOT_FOUND",
                "열차를 찾을 수 없습니다. 다시 검색해주세요.",
            )

        train = self._last_trains[train_index]
        loop = asyncio.get_running_loop()

        # Check if standby is available
        if self._is_srt:
            if not train.reserve_standby_available():
                raise RailServiceError(
                    "STANDBY_NOT_AVAILABLE",
                    "해당 열차는 예약대기가 불가능합니다.",
                )
        else:
            if not train.has_waiting_list():
                raise RailServiceError(
                    "STANDBY_NOT_AVAILABLE",
                    "해당 열차는 예약대기가 불가능합니다.",
                )

        # Build passenger list for RESERVE STANDBY (실제 구성 전달 - 할인 적용)
        if passengers is None:
            passengers = PassengerCount()
        passenger_list = self._build_reserve_passenger_list(passengers)

        logger.debug(f"Reserve standby passengers: {passengers}")

        try:
            if self._is_srt:
                # SRT has dedicated reserve_standby method
                option = getattr(SRTSeatType, seat_type.value)
                reserve_kwargs = {
                    "train": train,
                    "passengers": passenger_list,
                    "option": option,
                }
                if phone_number:
                    reserve_kwargs["mblPhone"] = phone_number

                reservation = await loop.run_in_executor(
                    None,
                    partial(self.client.reserve_standby, **reserve_kwargs),
                )
            else:
                # KTX handles standby through the regular reserve method
                # when train has no seats available
                option = getattr(ReserveOption, seat_type.value)

                reservation = await loop.run_in_executor(
                    None,
                    partial(
                        self.client.reserve,
                        train=train,
                        passengers=passenger_list,
                        option=option,
                    ),
                )

            return self._normalize_reservation(reservation)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Standby reservation failed: {error_msg}")

            if "대기" in error_msg and ("불가" in error_msg or "없" in error_msg):
                raise RailServiceError(
                    "STANDBY_NOT_AVAILABLE",
                    "해당 열차는 예약대기가 불가능합니다.",
                )
            elif "중복" in error_msg or "이미" in error_msg:
                raise RailServiceError(
                    "RESERVE_DUPLICATE",
                    get_error_message("RESERVE_DUPLICATE"),
                )
            raise RailServiceError(
                "STANDBY_FAILED",
                f"예약대기 신청 실패: {error_msg}",
            )

    def _normalize_reservation(
        self, reservation: Union[SRTReservation, KTXReservation]
    ) -> Dict[str, Any]:
        """Convert reservation object to unified format."""
        if self._is_srt:
            tickets = []
            for ticket in reservation.tickets:
                tickets.append(
                    {
                        "car": ticket.car,
                        "seat": ticket.seat,
                        "seat_type": str(getattr(ticket, "seat_type", "")),
                        "passenger_type": str(getattr(ticket, "passenger_type", "")),
                        "price": int(ticket.price) if ticket.price else 0,
                    }
                )

            return {
                "reservation_number": reservation.reservation_number,
                "train_name": reservation.train_name,
                "train_number": reservation.train_number,
                "dep_station": reservation.dep_station_name,
                "arr_station": reservation.arr_station_name,
                "dep_date": reservation.dep_date,
                "dep_time": reservation.dep_time,
                "arr_time": reservation.arr_time,
                "seat_count": reservation.seat_count,
                "total_cost": reservation.total_cost,
                "is_paid": reservation.is_paid,
                "is_waiting": getattr(reservation, "is_waiting", False),
                "payment_deadline": getattr(reservation, "payment_deadline", None),
                "tickets": tickets,
            }
        else:
            # KTX reservation normalization
            tickets = []
            if hasattr(reservation, "tickets"):
                for ticket in reservation.tickets:
                    tickets.append(
                        {
                            "car": getattr(ticket, "car", ""),
                            "seat": getattr(ticket, "seat", ""),
                            "seat_type": getattr(ticket, "seat_type", ""),
                            "passenger_type": getattr(ticket, "passenger_type", ""),
                            "price": int(getattr(ticket, "price", 0)),
                        }
                    )

            return {
                "reservation_number": reservation.rsv_id,
                "train_name": getattr(reservation, "train_name", ""),
                "train_number": getattr(reservation, "train_no", ""),
                "dep_station": getattr(reservation, "dep_name", ""),
                "arr_station": getattr(reservation, "arr_name", ""),
                "dep_date": getattr(reservation, "dep_date", ""),
                "dep_time": getattr(reservation, "dep_time", ""),
                "arr_time": getattr(reservation, "arr_time", ""),
                "seat_count": getattr(reservation, "seat_count", 1),
                "total_cost": int(getattr(reservation, "price", 0)),
                "is_paid": getattr(reservation, "is_paid", False),
                "is_waiting": getattr(reservation, "is_waiting", False),
                "payment_deadline": getattr(reservation, "payment_deadline", None),
                "tickets": tickets,
            }

    async def get_reservations(self) -> List[Dict[str, Any]]:
        """Get user's current reservations."""
        loop = asyncio.get_running_loop()

        try:
            if self._is_srt:
                reservations = await loop.run_in_executor(
                    None, self.client.get_reservations
                )
            else:
                reservations = await loop.run_in_executor(
                    None, self.client.reservations
                )

            return [self._normalize_reservation(r) for r in reservations]
        except Exception as e:
            logger.error(f"Failed to get reservations: {e}")
            return []

    async def cancel_reservation(self, reservation_number: str) -> bool:
        """Cancel a reservation."""
        loop = asyncio.get_running_loop()

        try:
            if self._is_srt:
                await loop.run_in_executor(
                    None, partial(self.client.cancel, reservation_number)
                )
            else:
                await loop.run_in_executor(
                    None, partial(self.client.cancel, reservation_number)
                )
            return True
        except Exception as e:
            logger.error(f"Failed to cancel reservation: {e}")
            return False

    async def pay_with_card(
        self,
        reservation_number: str,
        card_number: str,
        card_password: str,
        birth_or_business: str,
        expire_date: str,
        installment: int = 0,
        card_type: str = "J",
    ) -> Dict[str, Any]:
        """
        Pay for a reservation with credit card.

        Args:
            reservation_number: Reservation ID to pay for
            card_number: Card number (no hyphens, 15-16 digits)
            card_password: First 2 digits of card password
            birth_or_business: Birth date (YYMMDD) or business number
            expire_date: Card expiry date (YYMM)
            installment: Number of installments (0=lump sum, 2-12, 24)
            card_type: Card type (J=personal, S=corporate)

        Returns:
            Payment result dictionary with success status and details
        """
        loop = asyncio.get_running_loop()

        # First, get the reservation object
        try:
            if self._is_srt:
                reservations = await loop.run_in_executor(
                    None, self.client.get_reservations
                )
            else:
                reservations = await loop.run_in_executor(
                    None, self.client.reservations
                )

            # Find the matching reservation
            reservation = None
            for r in reservations:
                rsv_id = r.reservation_number if self._is_srt else r.rsv_id
                if rsv_id == reservation_number:
                    reservation = r
                    break

            if reservation is None:
                raise RailServiceError(
                    "PAYMENT_RESERVATION_NOT_FOUND",
                    f"예약번호 {reservation_number}를 찾을 수 없습니다.",
                )

            # Check if already paid
            is_paid = reservation.is_paid if self._is_srt else getattr(reservation, "is_paid", False)
            if is_paid:
                raise RailServiceError(
                    "PAYMENT_ALREADY_PAID",
                    "이미 결제가 완료된 예약입니다.",
                )

            # Get the total amount
            total_cost = reservation.total_cost if self._is_srt else int(getattr(reservation, "price", 0))

            # Make the payment
            if self._is_srt:
                success = await loop.run_in_executor(
                    None,
                    partial(
                        self.client.pay_with_card,
                        reservation=reservation,
                        number=card_number,
                        password=card_password,
                        validation_number=birth_or_business,
                        expire_date=expire_date,
                        installment=installment,
                        card_type=card_type,
                    ),
                )
            else:
                success = await loop.run_in_executor(
                    None,
                    partial(
                        self.client.pay_with_card,
                        rsv=reservation,
                        card_number=card_number,
                        card_password=card_password,
                        birthday=birth_or_business,
                        card_expire=expire_date,
                        installment=installment,
                        card_type=card_type,
                    ),
                )

            if success:
                return {
                    "success": True,
                    "reservation_number": reservation_number,
                    "amount_paid": total_cost,
                    "message": "결제가 완료되었습니다.",
                }
            else:
                raise RailServiceError(
                    "PAYMENT_FAILED",
                    "결제 처리 중 오류가 발생했습니다.",
                )

        except RailServiceError:
            raise
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Payment failed: {error_msg}")

            if "카드" in error_msg:
                raise RailServiceError(
                    "PAYMENT_CARD_ERROR",
                    f"카드 정보 오류: {error_msg}",
                )
            elif "비밀번호" in error_msg:
                raise RailServiceError(
                    "PAYMENT_PASSWORD_ERROR",
                    "카드 비밀번호가 올바르지 않습니다.",
                )
            raise RailServiceError(
                "PAYMENT_FAILED",
                f"결제 실패: {error_msg}",
            )

    def check_seat_available(self, train_index: int) -> Tuple[bool, bool, bool]:
        """
        Check seat availability for a train.

        Returns:
            Tuple of (general_available, special_available, standby_available)
        """
        if train_index >= len(self._last_trains):
            return False, False, False

        train = self._last_trains[train_index]

        if self._is_srt:
            return (
                train.general_seat_available(),
                train.special_seat_available(),
                train.reserve_standby_available(),
            )
        else:
            return (
                train.has_general_seat(),
                train.has_special_seat(),
                train.has_waiting_list(),
            )

    @staticmethod
    def _calc_duration(dep_time: str, arr_time: str) -> int:
        """Calculate trip duration in minutes."""
        try:
            dep = int(dep_time[:2]) * 60 + int(dep_time[2:4])
            arr = int(arr_time[:2]) * 60 + int(arr_time[2:4])
            if arr < dep:
                arr += 24 * 60  # Next day arrival
            return arr - dep
        except (ValueError, IndexError):
            return 0
