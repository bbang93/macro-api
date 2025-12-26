"""Settings router for managing user preferences and notifications."""

from typing import Dict
from fastapi import APIRouter, Header, HTTPException

from ..core.session import session_manager
from ..models.schemas import (
    TelegramSettingsRequest,
    TelegramSettingsResponse,
    NotificationTestResponse,
)
from ..services.notification_service import TelegramNotifier

router = APIRouter(prefix="/settings", tags=["settings"])

# Store notifiers per session
_session_notifiers: Dict[str, TelegramNotifier] = {}


def get_notifier(session_id: str) -> TelegramNotifier:
    """Get or create a notifier for the session."""
    if session_id not in _session_notifiers:
        _session_notifiers[session_id] = TelegramNotifier()
    return _session_notifiers[session_id]


@router.post("/telegram", response_model=TelegramSettingsResponse)
async def configure_telegram(
    settings: TelegramSettingsRequest,
    x_session_id: str = Header(...),
):
    """
    Configure Telegram notifications.

    Set up Telegram bot token and chat ID for receiving notifications.
    """
    session = session_manager.get_session(x_session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    notifier = get_notifier(x_session_id)
    notifier.configure(settings.bot_token, settings.chat_id)

    return TelegramSettingsResponse(
        enabled=notifier.enabled,
        chat_id=settings.chat_id[-4:].rjust(len(settings.chat_id), "*"),
    )


@router.get("/telegram", response_model=TelegramSettingsResponse)
async def get_telegram_settings(
    x_session_id: str = Header(...),
):
    """Get current Telegram notification settings."""
    session = session_manager.get_session(x_session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    notifier = get_notifier(x_session_id)

    # Mask chat_id for security
    masked_chat_id = None
    if notifier.chat_id:
        masked_chat_id = notifier.chat_id[-4:].rjust(len(notifier.chat_id), "*")

    return TelegramSettingsResponse(
        enabled=notifier.enabled,
        chat_id=masked_chat_id,
    )


@router.delete("/telegram")
async def disable_telegram(
    x_session_id: str = Header(...),
):
    """Disable Telegram notifications."""
    session = session_manager.get_session(x_session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    notifier = get_notifier(x_session_id)
    notifier.disable()

    return {"message": "Telegram notifications disabled"}


@router.post("/telegram/test", response_model=NotificationTestResponse)
async def test_telegram(
    x_session_id: str = Header(...),
):
    """
    Send a test notification.

    Use this to verify Telegram configuration is working correctly.
    """
    session = session_manager.get_session(x_session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    notifier = get_notifier(x_session_id)

    if not notifier.enabled:
        return NotificationTestResponse(
            success=False,
            message="텔레그램 알림이 설정되지 않았습니다.",
        )

    success = await notifier._send_message(
        "<b>🔔 테스트 알림</b>\n\n"
        "기차 예매 매크로 알림이 정상적으로 설정되었습니다.\n"
        "예매 성공 시 이 채팅으로 알림을 받게 됩니다."
    )

    if success:
        return NotificationTestResponse(
            success=True,
            message="테스트 알림이 전송되었습니다.",
        )
    else:
        return NotificationTestResponse(
            success=False,
            message="알림 전송에 실패했습니다. 토큰과 채팅 ID를 확인해주세요.",
        )


@router.post("/telegram/login", response_model=NotificationTestResponse)
async def send_login_notification(
    x_session_id: str = Header(...),
):
    """
    Send a login notification.

    Sends a notification when user logs in.
    """
    import logging
    logger = logging.getLogger(__name__)

    session = session_manager.get_session(x_session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")

    notifier = get_notifier(x_session_id)

    logger.info(f"[로그인알림] session_id={x_session_id[:8]}..., notifier.enabled={notifier.enabled}, bot_token={notifier.bot_token[:10] if notifier.bot_token else None}..., chat_id={notifier.chat_id}")

    if not notifier.enabled:
        return NotificationTestResponse(
            success=False,
            message="텔레그램 알림이 설정되지 않았습니다.",
        )

    success = await notifier.send_login_notification(
        rail_type=session.rail_type,
        user_name=session.user_info.get('name') or session.user_info.get('membership_number', 'Unknown'),
        membership_number=session.user_info.get('membership_number'),
    )

    logger.info(f"[로그인알림] send_login_notification 결과: {success}")

    if success:
        return NotificationTestResponse(
            success=True,
            message="로그인 알림이 전송되었습니다.",
        )
    else:
        return NotificationTestResponse(
            success=False,
            message="알림 전송에 실패했습니다.",
        )
