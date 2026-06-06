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


def _post_message(url: str, chat_id: str, text: str, parse_mode: str | None) -> requests.Response:
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return requests.post(url, json=payload, timeout=10)


def send_telegram_message(text: str, parse_mode: str = "Markdown") -> bool:
    """Telegram chat으로 메시지 전송. Markdown 파싱 실패 시 plain text 폴백.

    Returns:
        True 전송 성공, False 환경 변수 없음 또는 전송 실패 (예외는 안 던짐).
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False

    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    try:
        resp = _post_message(url, chat_id, text, parse_mode)
        if resp.status_code == 200:
            return True
        # 400 = 보통 Markdown 파싱 에러. 실제 에러 description 로깅 + plain text 재시도.
        if resp.status_code == 400 and parse_mode:
            try:
                err_body = resp.json()
                desc = err_body.get("description", resp.text[:200])
            except Exception:
                desc = resp.text[:200]
            print(f"[telegram] markdown parse failed ({desc}) — retry as plain text")
            resp2 = _post_message(url, chat_id, text, None)
            if resp2.status_code == 200:
                return True
            try:
                err2 = resp2.json().get("description", resp2.text[:200])
            except Exception:
                err2 = resp2.text[:200]
            print(f"[telegram] plain text also failed: {err2}")
            return False
        # 다른 status code
        try:
            err = resp.json().get("description", resp.text[:200])
        except Exception:
            err = resp.text[:200]
        print(f"[telegram] send failed: HTTP {resp.status_code} {err}")
        return False
    except Exception as e:
        print(f"[telegram] send failed (network): {e}")
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
      - 변함없음: 신호/가격/총자산을 함께 표시해 봇 정상 동작 검증 가능하게
      - 에러: 코드/메시지

    result 필수 키: signal, price, equity, cash, base_qty, trade (None 가능), duplicate_bar, bar_time.
    """
    mode_label = {
        "testnet": "📊 실투자 (테스트넷)",
        "mainnet": "🔥 실거래",
    }.get(mode, "📊 실투자 (테스트넷)")

    header = f"{mode_label} · {_kst_str()}"
    trade = result.get("trade")

    # CASE 1: 변함없음 (거래 없음)
    # 헬스체크 역할: 신호/가격/총자산이 매일 갱신되는지 확인 가능.
    if trade is None:
        bar_short = (result.get("bar_time") or "")[:10]
        signal = float(result.get("signal", 0))
        price = float(result.get("price", 0))
        equity = float(result.get("equity", 0))
        cash = float(result.get("cash", 0))
        base_qty = float(result.get("base_qty", 0))
        position_value = base_qty * price
        current_weight = (position_value / equity) if equity > 0 else 0.0

        if result.get("duplicate_bar"):
            reason = "같은 봉 재처리"
        else:
            reason = f"목표 {signal*100:.1f}% ↔ 현재 {current_weight*100:.1f}% (1% 미만 차이)"

        lines = [
            header,
            f"변함없음 ({reason})",
            "",
            f"🎯 신호: `{signal:.3f}` (기준 봉 {bar_short})",
            f"💰 현재가: `${price:,.2f}`",
            f"💼 총자산: `${equity:,.2f}`",
            f"  ├ 예수금: `${cash:,.2f}`",
            f"  └ BTC: `{base_qty:.6f}` (`${position_value:,.2f}`)",
        ]
        return "\n".join(lines)

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
