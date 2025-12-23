"""Custom exceptions for the Train Macro API."""

from typing import Dict, Any, Optional


class TrainMacroError(Exception):
    """Base exception for train macro API."""

    def __init__(
        self,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class AuthenticationError(TrainMacroError):
    """Login failed or invalid credentials."""

    pass


class SessionError(TrainMacroError):
    """Session invalid or expired."""

    pass


class ValidationError(TrainMacroError):
    """Request validation failed."""

    pass


class RailServiceError(TrainMacroError):
    """Error from SRT/KTX API."""

    pass


class NetFunnelError(TrainMacroError):
    """Traffic control queue error."""

    pass


# Error codes with Korean messages
ERROR_MESSAGES = {
    "AUTH_INVALID_CREDENTIALS": "아이디 또는 비밀번호가 올바르지 않습니다",
    "AUTH_ACCOUNT_LOCKED": "계정이 잠겼습니다. 잠시 후 다시 시도해주세요",
    "AUTH_IP_BLOCKED": "IP가 차단되었습니다",
    "SESSION_EXPIRED": "세션이 만료되었습니다. 다시 로그인해주세요",
    "SESSION_NOT_FOUND": "세션을 찾을 수 없습니다",
    "SESSION_MISSING": "세션 ID가 필요합니다",
    "TRAIN_SEARCH_NO_RESULTS": "검색 결과가 없습니다",
    "TRAIN_SEARCH_INVALID_STATION": "올바르지 않은 역 이름입니다",
    "TRAIN_SEARCH_INVALID_DATE": "올바르지 않은 날짜입니다",
    "RESERVE_SOLD_OUT": "매진되었습니다",
    "RESERVE_DUPLICATE": "이미 예약된 열차입니다",
    "RESERVE_LIMIT_EXCEEDED": "예약 한도를 초과했습니다",
    "RESERVE_FAILED": "예약에 실패했습니다",
    "NETFUNNEL_QUEUE": "대기열에서 기다리는 중입니다",
    "NETFUNNEL_ERROR": "서버가 혼잡합니다. 잠시 후 다시 시도해주세요",
    "JOB_NOT_FOUND": "작업을 찾을 수 없습니다",
    "JOB_ALREADY_RUNNING": "이미 실행 중인 작업입니다",
    "JOB_ALREADY_COMPLETED": "이미 완료된 작업입니다",
    "INTERNAL_ERROR": "내부 서버 오류가 발생했습니다",
}


def get_error_message(code: str) -> str:
    """Get localized error message for error code."""
    return ERROR_MESSAGES.get(code, code)
