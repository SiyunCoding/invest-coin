"""Telegram 봇 알림.

설정:
  - 환경 변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  - 둘 중 하나라도 비어있으면 send_telegram_message는 graceful no-op (False 반환)
  - 그래서 tick 로직은 알림 설정 안 했어도 안전하게 돌아감

봇 생성:
  1. @BotFather에서 /newbot → 봇 이름 + username → token 발급
  2. 만든 봇 검색해서 /start 한 번 보내기 (필수, 안 보내면 메시지 못 받음)
  3. @userinfobot 으로 자기 chat_id 확인
  4. GitHub Secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 등록
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

TELEGRAM_API = "https://api.telegram.org"


def send_telegram_message(text: str, parse_mode: str = "Markdown") -> bool:
    """Telegram chat으로 메시지 전송.

    Returns:
        True 전송 성공, False 환경 변수 없음 또는 전송 실패 (예외는 안 던짐).
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False

    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[telegram] send failed: {e}")
        return False


def _kst_str(dt: Optional[datetime] = None) -> str:
    if dt is None:
        dt = datetime.now(timezone.utc)
    kst = dt.astimezone(timezone(timedelta(hours=9)))
    return kst.strftime("%Y-%m-%d %H:%M KST")


def format_tick_notification(mode: str, result: dict) -> str:
    """Tick 결과 dict → Telegram Markdown 메시지.

    result 필수 키: signal, price, equity, cash, base_qty, trade (None 가능), duplicate_bar.
    """
    mode_emoji = {"paper": "🔵", "testnet": "🟢", "mainnet": "🔴"}.get(mode, "🔵")
    mode_label = {"paper": "Paper", "testnet": "Testnet", "mainnet": "MAINNET"}.get(mode, "Paper")

    signal = float(result.get("signal", 0.0))
    price = float(result.get("price", 0.0))
    equity = float(result.get("equity", 0.0))
    cash = float(result.get("cash", equity))
    qty = float(result.get("base_qty", 0.0))

    lines = [
        f"{mode_emoji} *{mode_label} Tick* — {_kst_str()}",
        "",
        f"Signal: `{signal:.3f}`",
        f"Equity: `${equity:,.2f}`",
        f"Cash: `${cash:,.2f}`",
        f"BTC: `{qty:.6f}` × `${price:,.2f}`",
        "",
    ]

    trade = result.get("trade")
    if trade is None:
        if result.get("duplicate_bar"):
            lines.append("🔁 Same bar as last tick — no action")
        else:
            lines.append("📝 No trade today")
    elif trade.get("side") == "error":
        lines.append(f"⚠️ ORDER ERROR")
        if "error_code" in trade:
            lines.append(f"Code: `{trade['error_code']}`")
        if "error_message" in trade:
            lines.append(f"Message: `{trade['error_message']}`")
    else:
        side = trade.get("side", "?").upper()
        side_emoji = "🚀" if side == "BUY" else "💰"
        t_qty = float(trade.get("qty", 0))
        t_price = float(trade.get("price", 0))
        t_value = float(trade.get("value", 0))
        t_fee = float(trade.get("fee", 0))
        lines.append(f"{side_emoji} *{side}* `{t_qty:.6f} BTC` @ `${t_price:,.2f}`")
        lines.append(f"Value: `${t_value:,.2f}` · Fee: `{t_fee:.6f} {trade.get('fee_asset', 'USDT')}`")

    return "\n".join(lines)
