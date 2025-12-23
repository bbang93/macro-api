"""Enumeration types for the API."""

from enum import Enum


class RailType(str, Enum):
    """Supported rail service types."""

    SRT = "SRT"
    KTX = "KTX"


class SeatType(str, Enum):
    """Seat preference options."""

    GENERAL_FIRST = "GENERAL_FIRST"  # 일반실 우선
    GENERAL_ONLY = "GENERAL_ONLY"  # 일반실만
    SPECIAL_FIRST = "SPECIAL_FIRST"  # 특실 우선
    SPECIAL_ONLY = "SPECIAL_ONLY"  # 특실만


class PassengerType(str, Enum):
    """Passenger types for fare calculation."""

    ADULT = "ADULT"  # 어른/청소년
    CHILD = "CHILD"  # 어린이
    SENIOR = "SENIOR"  # 경로
    DISABILITY_1_3 = "DISABILITY_1_3"  # 장애 1-3급
    DISABILITY_4_6 = "DISABILITY_4_6"  # 장애 4-6급
    TODDLER = "TODDLER"  # 유아 (KTX only)


class TrainType(str, Enum):
    """Train types for filtering (KTX only)."""

    KTX = "KTX"  # KTX (일반)
    KTX_SANCHEON = "KTX-산천"  # KTX-산천
    ITX_SAEMAEUL = "ITX-새마을"  # ITX-새마을
    ITX_CHEONGCHUN = "ITX-청춘"  # ITX-청춘
    MUGUNGHWA = "무궁화"  # 무궁화호
    SAEMAEUL = "새마을"  # 새마을호
    NURIRO = "누리로"  # 누리로
    TONGGEUN = "통근열차"  # 통근열차
    AIRPORT = "공항철도"  # 공항철도


class JobStatus(str, Enum):
    """Macro job status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
