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
    """Tick 결과 dict → 한국어 Telegram Markdown 메시지.

    원칙:
      - 매매 발생: 체결 정보 + 잔고 현황 풍부하게
      - 변함없음: "변함없음" 한 줄
      - 에러: 코드/메시지

    result 필수 키: signal, price, equity, cash, base_qty, trade (None 가능), duplicate_bar.
    """
    mode_label = {
        "paper": "📊 모의투자",
        "testnet": "📊 실투자 (테스트넷)",
        "mainnet": "🔥 실거래",
    }.get(mode, "📊 모의투자")

    header = f"{mode_label} · {_kst_str()}"
    trade = result.get("trade")

    # CASE 1: 변함없음 (거래 없음)
    if trade is None:
        if result.get("duplicate_bar"):
            return f"{header}\n변함없음 (같은 봉)"
        return f"{header}\n변함없음"

    # CASE 2: 주문 오류
    if trade.get("side") == "error":
        lines = [header, "", "⚠️ *주문 오류*"]
        if "error_code" in trade:
            lines.append(f"• 에러 코드: `{trade['error_code']}`")
        if "error_message" in trade:
            lines.append(f"• 메시지: `{trade['error_message']}`")
        return "\n".join(lines)

    # CASE 3: 매수/매도 체결
    side = trade.get("side", "").upper()
    side_emoji = "🚀" if side == "BUY" else "💰"
    side_label = "매수" if side == "BUY" else "매도"
    symbol = trade.get("symbol", "BTCUSDT")
    t_qty = float(trade.get("qty", 0))
    t_price = float(trade.get("price", 0))
    t_value = float(trade.get("value", 0))
    t_fee = float(trade.get("fee", 0))
    fee_asset = trade.get("fee_asset", "USDT")

    equity = float(result.get("equity", 0))
    cash = float(result.get("cash", 0))
    base_qty = float(result.get("base_qty", 0))
    current_price = float(result.get("price", t_price))
    position_value = base_qty * current_price

    lines = [
        header,
        "",
        f"{side_emoji} *{side_label} 체결*",
        f"• 종목: `{symbol}`",
        f"• 수량: `{t_qty:.6f} BTC`",
        f"• 체결가: `${t_price:,.2f}`",
        f"• 체결금액: `${t_value:,.2f}`",
        f"• 수수료: `{t_fee:.6f} {fee_asset}`",
        "",
        "💼 *잔고 현황*",
        f"• 총자산: `${equity:,.2f}`",
        f"• 평가금액: `${position_value:,.2f}` (BTC {base_qty:.6f})",
        f"• 예수금: `${cash:,.2f}`",
    ]
    return "\n".join(lines)
