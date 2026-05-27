"""한 번의 Futures Scalping Tick (50x SHORT on RSI 5m > 70).

흐름:
  1. Binance에서 현재 포지션 + 사용 가능 마진 조회
  2. 5분봉 데이터 받아서 RSI(14) 계산
  3. 포지션 있으면: 기다림 (TP가 서버에서 자동 처리 중)
  4. 포지션 없으면:
     - RSI > 70 → SHORT 진입 + TP 자동 청산 주문
     - RSI ≤ 70 → 진입 안 함
  5. state.json + Telegram 알림

설계:
  - source of truth = Binance (포지션은 매 tick 재조회)
  - 손절 없음 (Binance가 −100% 마진에서 자동 청산)
  - 익절은 TAKE_PROFIT_MARKET 서버 사이드 주문
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from binance.exceptions import BinanceAPIException

from ..common import load_state, save_state
from ..notifier import send_telegram_message
from ..utils import wilder_rsi
from .futures_client import get_futures_client
from .futures_executor import (
    cancel_all_open_orders,
    ensure_leverage_and_margin,
    get_available_balance,
    get_mark_price,
    get_position_amt,
    open_short_with_tp,
)


def _init_state(config: dict, started_at: str, initial_balance: float) -> dict:
    return {
        "config": config,
        "initial_balance": initial_balance,
        "trades": [],
        "history": [],
        "peak_balance": initial_balance,
        "started_at": started_at,
        "last_tick": None,
        "last_rsi": None,
        "last_price": None,
        "current_position": None,  # {qty, entry_price, tp_stop_price, entered_at}
        "mode": "futures-demo" if config.get("demo", True) else "futures-mainnet",
    }


def _fetch_rsi_5m(client, symbol: str, period: int = 14, limit: int = 100) -> float:
    """선물 5분봉 받아서 마지막 RSI 값 반환. 마감된 봉만 사용."""
    klines = client.futures_klines(symbol=symbol, interval="5m", limit=limit)
    # kline 컬럼: [open_time, open, high, low, close, volume, close_time, ...]
    closes = pd.Series([float(k[4]) for k in klines])
    close_times = [int(k[6]) for k in klines]
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    # 마지막 봉이 미마감(close_time > now)이면 그 봉 제외
    if close_times[-1] > now_ms:
        closes = closes.iloc[:-1]
    rsi = wilder_rsi(closes, period=period)
    return float(rsi.iloc[-1])


def _format_entry_notification(mode: str, result: dict) -> str:
    """진입 직후 텔레그램 메시지."""
    from datetime import timedelta
    kst = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9)))
    header = f"📉 선물 SHORT 진입 ({mode}) · {kst.strftime('%Y-%m-%d %H:%M KST')}"
    lines = [
        header,
        "",
        f"• 종목: `{result['symbol']}`",
        f"• 진입가: `${result['entry_price']:,.2f}`",
        f"• 수량: `{result['qty']:.6f} BTC` (노셔널 `${result['notional']:,.0f}`)",
        f"• 마진: `${result['margin_usdt']:.2f}` × {result['leverage']}x",
        f"• RSI(5m): `{result['rsi']:.2f}`",
        "",
        f"🎯 TP 자동 청산 주문: `${result['tp_stop_price']:,.2f}` (가격 −{result['drop_pct']:.3f}%)",
        f"💰 예상 순익: `${result['expected_net_profit']:.2f}` (수수료 `${result['estimated_fees']:.2f}` 별도)",
        f"⚠️ 청산가 (Binance 자동): `${result['liquidation_price_est']:,.2f}` (가격 +{result['liq_pct']:.2f}%)",
    ]
    return "\n".join(lines)


def _format_idle_notification(mode: str, rsi: float, price: float, balance: float, position: dict | None) -> str:
    """진입 없음 / 포지션 보유 중 알림."""
    from datetime import timedelta
    kst = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9)))
    header = f"📊 선물 스캘핑 ({mode}) · {kst.strftime('%Y-%m-%d %H:%M KST')}"
    if position is not None:
        return "\n".join([
            header,
            "포지션 보유 중 (TP 대기)",
            "",
            f"🎯 SHORT qty: `{position['qty']:.6f} BTC`",
            f"📌 진입가: `${position['entry_price']:,.2f}`",
            f"💰 현재가: `${price:,.2f}`",
            f"🎁 TP 목표: `${position['tp_stop_price']:,.2f}`",
            f"📊 RSI(5m): `{rsi:.2f}`",
        ])
    return "\n".join([
        header,
        f"진입 대기 (RSI {rsi:.2f} ≤ 70)",
        "",
        f"💰 현재가: `${price:,.2f}`",
        f"💼 가용 마진: `${balance:,.2f}`",
    ])


def run_futures_tick(
    state_path: Path,
    config: dict,
) -> dict:
    """Futures scalping tick 한 번 실행."""
    now = datetime.now(timezone.utc)
    demo = bool(config.get("demo", True))
    symbol = config["symbol"]
    leverage = int(config["leverage"])
    margin_usdt = float(config["margin_usdt"])
    tp_profit_pct = float(config["tp_profit_pct"])
    cushion_usdt = float(config.get("cushion_usdt", 2.0))
    rsi_threshold = float(config.get("rsi_threshold", 70.0))
    rsi_period = int(config.get("rsi_period", 14))

    client = get_futures_client(demo=demo)
    mode = "futures-demo" if demo else "futures-mainnet"

    # 0. 잔고 + 포지션 + 가격 조회
    balance = get_available_balance(client, "USDT")
    position_amt = get_position_amt(client, symbol)  # SHORT면 음수
    mark_price = get_mark_price(client, symbol)

    # State 로드 (또는 초기화)
    state = load_state(state_path)
    if state is None:
        state = _init_state(config, now.isoformat(), balance)

    # 레버리지/마진 모드 최초 1회 설정 (idempotent)
    if not state.get("leverage_initialized"):
        ensure_leverage_and_margin(
            client, symbol, leverage, margin_type=config.get("margin_type", "CROSSED")
        )
        state["leverage_initialized"] = True

    # 1. RSI 계산
    rsi = _fetch_rsi_5m(client, symbol, period=rsi_period)

    # 2. 포지션 상태별 분기
    notification_text = None
    new_trade = None

    has_position = abs(position_amt) > 1e-9
    if has_position:
        # TP가 서버에서 처리 중. idle 알림만.
        pos = state.get("current_position") or {
            "qty": abs(position_amt),
            "entry_price": mark_price,  # 모르면 현재가로 fallback
            "tp_stop_price": 0,
        }
        notification_text = _format_idle_notification(mode, rsi, mark_price, balance, pos)
    else:
        # 포지션 없음. 직전 TP 체결이 있었나 확인 + 청산기록 정리
        prev_pos = state.get("current_position")
        if prev_pos is not None:
            # 직전에 포지션 있었는데 지금은 없음 = TP 체결 or 청산됨
            close_event = {
                "time": now.isoformat(),
                "type": "position_closed",
                "qty": prev_pos["qty"],
                "entry_price": prev_pos["entry_price"],
                "tp_stop_price": prev_pos.get("tp_stop_price"),
                "balance_after": balance,
            }
            state["trades"].append(close_event)
            state["current_position"] = None

        # RSI 진입 신호?
        if rsi > rsi_threshold:
            # 묵은 TP 주문 있으면 정리
            cancel_all_open_orders(client, symbol)
            try:
                result = open_short_with_tp(
                    client,
                    symbol=symbol,
                    margin_usdt=margin_usdt,
                    leverage=leverage,
                    tp_profit_pct=tp_profit_pct,
                    cushion_usdt=cushion_usdt,
                )
            except BinanceAPIException as e:
                err_trade = {
                    "time": now.isoformat(),
                    "type": "error",
                    "error_code": e.code,
                    "error_message": str(e.message),
                    "rsi": rsi,
                }
                state["trades"].append(err_trade)
                notification_text = (
                    f"⚠️ 선물 진입 오류 ({mode})\n"
                    f"• 코드: `{e.code}`\n"
                    f"• 메시지: `{e.message}`"
                )
            else:
                # 청산가 추정 (cross 50x): 가격 +1/leverage = liquidation
                liq_price_est = result["entry_price"] * (1 + 1.0 / leverage)
                drop_pct = (result["entry_price"] - result["tp_stop_price"]) / result["entry_price"] * 100
                liq_pct = (liq_price_est - result["entry_price"]) / result["entry_price"] * 100

                new_trade = {
                    "time": now.isoformat(),
                    "type": "entry",
                    "side": "SHORT",
                    "symbol": symbol,
                    "qty": result["qty"],
                    "entry_price": result["entry_price"],
                    "tp_stop_price": result["tp_stop_price"],
                    "leverage": leverage,
                    "margin_usdt": margin_usdt,
                    "notional": result["notional"],
                    "expected_net_profit": result["expected_net_profit"],
                    "estimated_fees": result["estimated_fees"],
                    "rsi": rsi,
                    "entry_order_id": result["entry"].get("orderId"),
                    "tp_order_id": result["tp"].get("orderId"),
                }
                state["trades"].append(new_trade)
                state["current_position"] = {
                    "qty": result["qty"],
                    "entry_price": result["entry_price"],
                    "tp_stop_price": result["tp_stop_price"],
                    "entered_at": now.isoformat(),
                }
                notification_text = _format_entry_notification(
                    mode,
                    {
                        **result,
                        "symbol": symbol,
                        "rsi": rsi,
                        "drop_pct": drop_pct,
                        "liquidation_price_est": liq_price_est,
                        "liq_pct": liq_pct,
                    },
                )
        else:
            notification_text = _format_idle_notification(mode, rsi, mark_price, balance, None)

    # 3. State 갱신 + 히스토리 추가
    state["history"].append({
        "time": now.isoformat(),
        "rsi": rsi,
        "price": mark_price,
        "balance": balance,
        "has_position": has_position or new_trade is not None,
    })
    state["last_tick"] = now.isoformat()
    state["last_rsi"] = rsi
    state["last_price"] = mark_price
    state["mode"] = mode
    if balance > state.get("peak_balance", 0):
        state["peak_balance"] = balance

    save_state(state_path, state)

    if notification_text:
        send_telegram_message(notification_text)

    return {
        "rsi": rsi,
        "price": mark_price,
        "balance": balance,
        "position_amt": position_amt,
        "new_trade": new_trade,
        "mode": mode,
    }
