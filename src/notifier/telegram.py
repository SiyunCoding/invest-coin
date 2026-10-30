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

import requests

from ..utils.timefmt import kst_str

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
        # requests 예외 메시지에는 요청 URL(= 봇 토큰 포함)이 들어감 → 토큰 가림
        print(f"[telegram] send failed (network): {str(e).replace(token, '***')}")
        return False



def format_portfolio_notification(result: dict) -> str:
    """Trend Rotation tick 결과 → 한국어 Telegram Markdown 메시지.

    result: src.live.portfolio_tick.run_portfolio_tick 반환값.
    매 tick 헬스체크 역할 — 총자산/노출/종목별 비중을 항상 표시, 체결·정지·오류는 강조.
    """
    mode_label = {"testnet": "📊 실투자 (테스트넷)", "mainnet": "🔥 실거래"}.get(result.get("mode"), "📊 테스트넷")
    lines = [f"{mode_label} · {kst_str()}"]

    if result.get("halted") or result.get("buy_blocked"):
        title = "🛑 *매매 정지*" if result.get("halted") else "⚠️ *매수 중지 (매도만 허용)*"
        lines += ["", title] + [f"• {r}" for r in result.get("reasons", [])]

    trades = result.get("trades") or []
    fills = [t for t in trades if t.get("side") in ("buy", "sell")]
    errors = [t for t in trades if t.get("side") == "error"]
    if fills:
        lines += ["", f"🔁 *리밸런스 {len(fills)}건*"]
        for t in fills:
            emoji = "🚀 매수" if t["side"] == "buy" else "💰 매도"
            lines.append(f"• {emoji} `{t['symbol']}` `${float(t.get('value', 0)):,.2f}` @ `{float(t.get('price', 0)):,.4f}`")
    elif not result.get("duplicate_bar"):
        lines += ["", "변함없음 (밴드 안 — 리밸런스 불필요)"]
    else:
        lines += ["", "변함없음 (같은 봉 재처리)"]
    for t in errors:
        lines.append(f"⚠️ `{t.get('symbol')}` {t.get('attempted')} 실패 `{t.get('error_code')}` {str(t.get('error_message'))[:80]}")

    equity = float(result.get("equity", 0))
    lines += [
        "",
        f"💼 총자산 `${equity:,.2f}` · 노출 `{float(result.get('exposure', 0))*100:.1f}%`",
        f"📈 누적 `{(float(result.get('nav', 1)) - 1)*100:+.2f}%` (BTC 보유 `{float(result.get('btc_return', 0))*100:+.2f}%`)",
    ]
    weights = result.get("weights") or {}
    if weights:
        top = sorted(weights.items(), key=lambda kv: -kv[1])[:8]
        lines.append("📦 " + " · ".join(f"`{s.replace('USDT', '')}` {w*100:.1f}%" for s, w in top))
    if abs(float(result.get("external_flow", 0))) > 0:
        lines.append(f"ℹ️ 외부 입출금 감지 `${float(result['external_flow']):+,.2f}` (성과에서 제외)")
    if result.get("untradable"):
        lines.append(f"ℹ️ 이 계정에서 거래 불가: {', '.join(result['untradable'])}")
    if not result.get("alts_enabled", True):
        lines.append("ℹ️ 소액 계좌 → BTC 단독 운용")
    return "\n".join(lines)
