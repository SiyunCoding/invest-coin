"""알림 모듈 — Telegram 메시지로 tick 결과 전송.

환경 변수가 없으면 graceful no-op (에러 안 던짐).
"""
from .telegram import format_tick_notification, send_telegram_message

__all__ = ["format_tick_notification", "send_telegram_message"]
