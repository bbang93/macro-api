"""Pydantic schemas for request/response validation."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from .enums import RailType, SeatType, JobStatus, TrainType


# ============ Passenger Schemas ============


class PassengerCount(BaseModel):
    """Passenger count by type for fare calculation."""

    adult: int = Field(default=1, ge=0, le=9, description="어른/청소년 인원")
    child: int = Field(default=0, ge=0, le=9, description="어린이 인원")
    senior: int = Field(default=0, ge=0, le=9, description="경로 인원")
    disability_1_3: int = Field(default=0, ge=0, le=9, description="장애 1~3급 인원")
    disability_4_6: int = Field(default=0, ge=0, le=9, description="장애 4~6급 인원")
    toddler: int = Field(default=0, ge=0, le=9, description="유아 인원 (KTX only)")

    @property
    def total(self) -> int:
        """Total passenger count."""
        return (
            self.adult
            + self.child
            + self.senior
            + self.disability_1_3
            + self.disability_4_6
            + self.toddler
        )

    def validate_total(self) -> bool:
        """Validate total passenger count is within limits."""
        return 1 <= self.total <= 9


# ============ Auth Schemas ============


class LoginRequest(BaseModel):
    """Login request body."""

    rail_type: RailType
    user_id: str = Field(..., min_length=1, description="회원번호, 이메일, 또는 전화번호")
    password: str = Field(..., min_length=1, description="비밀번호")


class LoginResponse(BaseModel):
    """Login response with session info."""

    session_id: str
    expires_at: datetime
    rail_type: RailType
    user_name: Optional[str] = None
    membership_number: Optional[str] = None


class SessionResponse(BaseModel):
    """Session validity check response."""

    valid: bool
    expires_at: Optional[datetime] = None
    rail_type: Optional[RailType] = None


# ============ Station Schemas ============


class StationsResponse(BaseModel):
    """Available stations list."""

    rail_type: RailType
    stations: List[str]


# ============ Train Search Schemas ============


class TrainSearchRequest(BaseModel):
    """Train search request body."""

    departure: str = Field(..., description="출발역")
    arrival: str = Field(..., description="도착역")
    date: str = Field(..., pattern=r"^\d{8}$", description="날짜 (YYYYMMDD)")
    time: str = Field(default="000000", pattern=r"^\d{6}$", description="시간 (HHMMSS)")
    passengers: PassengerCount = Field(default_factory=PassengerCount, description="승객 유형별 인원")
    train_types: Optional[List[TrainType]] = Field(default=None, description="필터링할 열차 유형 (KTX only)")


class Train(BaseModel):
    """Train schedule information."""

    index: int
    train_code: str
    train_name: str
    train_number: str
    dep_station: str
    arr_station: str
    dep_date: str
    dep_time: str
    arr_time: str
    duration_minutes: int
    general_seat_available: bool
    special_seat_available: bool
    standby_available: bool


# ============ Job Schemas ============


class JobCreateRequest(BaseModel):
    """Macro job creation request."""

    departure: str
    arrival: str
    date: str = Field(..., pattern=r"^\d{8}$")
    time: str = Field(default="000000", pattern=r"^\d{6}$")
    passengers: PassengerCount = Field(default_factory=PassengerCount, description="승객 유형별 인원")
    seat_type: SeatType = SeatType.GENERAL_FIRST
    selected_trains: List[int] = Field(..., min_length=1, description="선택한 열차 인덱스 목록")
    prefer_window: bool = Field(default=False, description="창가석 우선 (SRT only)")
    use_standby: bool = Field(default=False, description="예약대기 사용 여부")
    train_types: Optional[List[TrainType]] = Field(default=None, description="필터링할 열차 유형 (KTX only)")


class Job(BaseModel):
    """Macro job status."""

    id: str
    status: JobStatus
    departure: str
    arrival: str
    date: str
    time: str
    passengers: PassengerCount
    seat_type: SeatType
    selected_trains: List[int]
    prefer_window: bool = False
    use_standby: bool = False
    train_types: Optional[List[TrainType]] = None
    attempt_count: int = 0
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional["Reservation"] = None
    error: Optional[str] = None


# ============ Reservation Schemas ============


class Ticket(BaseModel):
    """Individual ticket information."""

    car: str
    seat: str
    seat_type: str
    passenger_type: str
    price: int


class Reservation(BaseModel):
    """Reservation information."""

    reservation_number: str
    train_name: str
    train_number: str
    dep_station: str
    arr_station: str
    dep_date: str
    dep_time: str
    arr_time: str
    seat_count: int
    total_cost: int
    is_paid: bool
    is_waiting: bool
    payment_deadline: Optional[str] = None
    tickets: List[Ticket] = []


# ============ Payment Schemas ============


class PaymentRequest(BaseModel):
    """Credit card payment request."""

    card_number: str = Field(
        ...,
        min_length=15,
        max_length=16,
        pattern=r"^\d{15,16}$",
        description="카드번호 (숫자만, 15-16자리)",
    )
    card_password: str = Field(
        ...,
        min_length=2,
        max_length=2,
        pattern=r"^\d{2}$",
        description="카드 비밀번호 앞 2자리",
    )
    birth_or_business: str = Field(
        ...,
        min_length=6,
        max_length=10,
        description="생년월일 (YYMMDD) 또는 사업자번호",
    )
    expire_date: str = Field(
        ...,
        min_length=4,
        max_length=4,
        pattern=r"^\d{4}$",
        description="유효기간 (YYMM)",
    )
    installment: int = Field(
        default=0,
        ge=0,
        le=24,
        description="할부 개월 (0=일시불, 2-12, 24)",
    )
    card_type: str = Field(
        default="J",
        pattern=r"^[JS]$",
        description="카드 유형 (J=개인, S=법인)",
    )


class PaymentResponse(BaseModel):
    """Payment result response."""

    success: bool
    reservation_number: str
    amount_paid: int
    message: str


# ============ Notification Schemas ============


class TelegramSettingsRequest(BaseModel):
    """Telegram notification settings request."""

    bot_token: str = Field(..., min_length=1, description="텔레그램 봇 토큰")
    chat_id: str = Field(..., min_length=1, description="텔레그램 채팅 ID")


class TelegramSettingsResponse(BaseModel):
    """Telegram notification settings response."""

    enabled: bool
    chat_id: Optional[str] = None


class NotificationTestResponse(BaseModel):
    """Notification test result."""

    success: bool
    message: str


# ============ Error Schemas ============


class ErrorDetail(BaseModel):
    """Error detail information."""

    code: str
    message: str
    details: Dict[str, Any] = {}


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: ErrorDetail


# Update forward references
Job.model_rebuild()
