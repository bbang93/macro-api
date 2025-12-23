"""Notification service for sending alerts via Telegram."""

import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """
    Sends notifications via Telegram Bot API.

    Usage:
        notifier = TelegramNotifier(bot_token="...", chat_id="...")
        await notifier.send_reservation_success(reservation_data)
    """

    BASE_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        """
        Initialize Telegram notifier.

        Args:
            bot_token: Telegram bot API token
            chat_id: Target chat ID for notifications
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._enabled = bool(bot_token and chat_id)

    @property
    def enabled(self) -> bool:
        """Check if notifications are enabled."""
        return self._enabled

    def configure(self, bot_token: str, chat_id: str) -> None:
        """Configure or reconfigure the notifier."""
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._enabled = bool(bot_token and chat_id)

    def disable(self) -> None:
        """Disable notifications."""
        self._enabled = False

    async def _send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Send a message via Telegram Bot API.

        Args:
            text: Message text (supports HTML formatting)
            parse_mode: Message parse mode (HTML or Markdown)

        Returns:
            True if message was sent successfully
        """
        if not self._enabled:
            logger.debug("Telegram notifications disabled, skipping message")
            return False

        url = self.BASE_URL.format(token=self.bot_token)
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()

                result = response.json()
                if result.get("ok"):
                    logger.info("Telegram notification sent successfully")
                    return True
                else:
                    logger.error(f"Telegram API error: {result.get('description')}")
                    return False

        except httpx.TimeoutException:
            logger.error("Telegram notification timed out")
            return False
        except httpx.HTTPStatusError as e:
            logger.error(f"Telegram HTTP error: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Telegram notification failed: {e}")
            return False

    async def send_reservation_success(
        self,
        reservation: Dict[str, Any],
        is_standby: bool = False,
    ) -> bool:
        """
        Send reservation success notification.

        Args:
            reservation: Reservation data dictionary
            is_standby: Whether this is a standby reservation

        Returns:
            True if notification was sent successfully
        """
        reservation_type = "예약대기" if is_standby else "예매"

        message = f"""
<b>🎉 {reservation_type} 성공!</b>

<b>예약번호:</b> <code>{reservation.get('reservation_number', 'N/A')}</code>
<b>열차:</b> {reservation.get('train_name', '')} {reservation.get('train_number', '')}
<b>구간:</b> {reservation.get('dep_station', '')} → {reservation.get('arr_station', '')}
<b>출발:</b> {self._format_datetime(reservation.get('dep_date'), reservation.get('dep_time'))}
<b>도착:</b> {reservation.get('arr_time', '')[:2]}:{reservation.get('arr_time', '')[2:4] if len(reservation.get('arr_time', '')) >= 4 else ''}
<b>좌석수:</b> {reservation.get('seat_count', 0)}석
<b>금액:</b> {reservation.get('total_cost', 0):,}원
<b>결제상태:</b> {'결제완료' if reservation.get('is_paid') else '미결제'}
"""

        if reservation.get('payment_deadline'):
            message += f"\n<b>결제기한:</b> {reservation.get('payment_deadline')}"

        if is_standby:
            message += "\n\n⏳ <i>예약대기 상태입니다. 좌석 배정 시 SMS로 안내됩니다.</i>"

        return await self._send_message(message.strip())

    async def send_job_started(
        self,
        departure: str,
        arrival: str,
        date: str,
        selected_train_count: int,
    ) -> bool:
        """
        Send job started notification.

        Args:
            departure: Departure station
            arrival: Arrival station
            date: Travel date
            selected_train_count: Number of selected trains

        Returns:
            True if notification was sent successfully
        """
        message = f"""
<b>🚄 매크로 시작</b>

<b>구간:</b> {departure} → {arrival}
<b>날짜:</b> {self._format_date(date)}
<b>대상 열차:</b> {selected_train_count}개

조회를 시작합니다. 예매 성공 시 알림을 보내드립니다.
"""
        return await self._send_message(message.strip())

    async def send_job_failed(
        self,
        departure: str,
        arrival: str,
        error_message: str,
        attempt_count: int,
    ) -> bool:
        """
        Send job failure notification.

        Args:
            departure: Departure station
            arrival: Arrival station
            error_message: Error description
            attempt_count: Total attempts made

        Returns:
            True if notification was sent successfully
        """
        message = f"""
<b>❌ 매크로 실패</b>

<b>구간:</b> {departure} → {arrival}
<b>시도 횟수:</b> {attempt_count}회
<b>실패 원인:</b> {error_message}

매크로가 종료되었습니다.
"""
        return await self._send_message(message.strip())

    async def send_error(self, error_message: str, context: Optional[str] = None) -> bool:
        """
        Send error notification.

        Args:
            error_message: Error description
            context: Additional context about the error

        Returns:
            True if notification was sent successfully
        """
        message = f"""
<b>⚠️ 오류 발생</b>

<b>내용:</b> {error_message}
"""
        if context:
            message += f"\n<b>상세:</b> {context}"

        message += f"\n\n<i>발생시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"

        return await self._send_message(message.strip())

    async def send_session_expired(self, rail_type: str) -> bool:
        """
        Send session expired notification.

        Args:
            rail_type: Type of rail service (SRT/KTX)

        Returns:
            True if notification was sent successfully
        """
        message = f"""
<b>🔐 세션 만료</b>

{rail_type} 세션이 만료되었습니다.
다시 로그인해주세요.
"""
        return await self._send_message(message.strip())

    @staticmethod
    def _format_datetime(date_str: Optional[str], time_str: Optional[str]) -> str:
        """Format date and time strings for display."""
        if not date_str:
            return "N/A"

        formatted = f"{date_str[:4]}.{date_str[4:6]}.{date_str[6:8]}"
        if time_str and len(time_str) >= 4:
            formatted += f" {time_str[:2]}:{time_str[2:4]}"
        return formatted

    @staticmethod
    def _format_date(date_str: Optional[str]) -> str:
        """Format date string for display."""
        if not date_str or len(date_str) < 8:
            return date_str or "N/A"
        return f"{date_str[:4]}.{date_str[4:6]}.{date_str[6:8]}"


# Global notifier instance (can be configured per session)
telegram_notifier = TelegramNotifier()
