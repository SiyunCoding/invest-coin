"""한 번의 Live (testnet/mainnet) trading tick.

paper.tick 과 같은 구조이지만:
  - 가격 데이터: 그대로 load_ohlcv (Binance 또는 CC 폴백)
  - 신호 계산: 동일
  - 매매 실행: Binance API 호출 (paper는 JSON 시뮬레이션이었음)
  - 잔고 / 가격: 매 tick마다 Binance에서 조회 (source of truth)
  - 거래 로그 + history: state.json에 저장 (대시보드용)
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from binance.exceptions import BinanceAPIException

from ..data import load_ohlcv
from ..notifier import format_tick_notification, send_telegram_message
from ..paper.dashboard import render_dashboard
from ..paper.state import load_state, save_state
from ..strategies import REGISTRY
from .client import get_client
from .executor import (
    get_balances,
    get_current_price,
    rebalance_to_target,
    split_symbol,
)


def _init_live_state(config: dict, started_at: str, initial: float) -> dict:
    """페이퍼와 같은 스키마 — 대시보드 재사용 가능. testnet 플래그만 추가."""
    return {
        "config": {**config, "initial_capital": initial},
        "cash": initial,  # 다음 tick에서 Binance 조회로 갱신됨
        "position": {"qty": 0.0, "avg_cost": 0.0},
        "trades": [],
        "history": [],
        "peak_equity": initial,
        "started_at": started_at,
        "last_tick": None,
        "last_price": None,
        "last_signal": None,
        "last_bar_time": None,
        "mode": "testnet" if config.get("testnet", True) else "mainnet",
    }


def _compute_avg_cost(trades: list, base_qty: float) -> float:
    """매수 거래만 가중평균해 cost basis 추정. 현재 잔고 수량을 초과하지 않게 보정.

    Binance는 cost basis를 안 줘서 trade log로 추적해야 함.
    완벽하진 않지만 (FIFO/LIFO 가정 차이) 디스플레이용으로는 충분.
    """
    if base_qty <= 0 or not trades:
        return 0.0
    # 최근 매수부터 뒤로 가면서 base_qty까지만 채움
    remaining = base_qty
    weighted = 0.0
    for t in reversed(trades):
        if t["side"] != "buy" or t.get("qty", 0) <= 0:
            continue
        take = min(remaining, float(t["qty"]))
        weighted += take * float(t["price"])
        remaining -= take
        if remaining <= 1e-12:
            break
    return weighted / base_qty if base_qty > 0 else 0.0


def run_live_tick(
    state_path: Path,
    dashboard_path: Path,
    config: dict,
    cache_dir: Path | str = "data",
) -> dict:
    """Live tick 한 번 실행. dict 결과 반환."""
    now = datetime.now(timezone.utc)
    testnet = bool(config.get("testnet", True))
    client = get_client(testnet=testnet)
    symbol = config["symbol"]
    base, quote = split_symbol(symbol)

    # 0. Binance 현 상태 먼저 조회 (state 초기화 시 사용)
    base_qty, quote_qty = get_balances(client, base, quote)
    current_price = get_current_price(client, symbol)
    equity = quote_qty + base_qty * current_price

    state = load_state(state_path)
    if state is None:
        state = _init_live_state(config, now.isoformat(), equity)

    # 1. OHLCV → 신호
    ohlcv = load_ohlcv(
        symbol=symbol,
        interval=config["interval"],
        lookback_days=config.get("lookback_days", 730),
        cache_dir=cache_dir,
    )
    if ohlcv.empty:
        raise RuntimeError(f"No OHLCV data for {symbol}")

    meta = REGISTRY[config["strategy"]]
    strategy = meta.cls(**config.get("strategy_params", {}))
    signals = strategy.generate_signals(ohlcv)
    latest_signal = float(signals.iloc[-1])
    latest_bar_time = ohlcv.index[-1].isoformat()

    # 2. 같은 봉 두 번 처리 방지
    already_processed = state.get("last_bar_time") == latest_bar_time
    trade = None
    if not already_processed:
        try:
            trade = rebalance_to_target(client, symbol, latest_signal)
        except BinanceAPIException as e:
            # 주문 거부 등은 state에 기록만 하고 다음 tick에 재시도
            trade = {
                "time": now.isoformat(),
                "side": "error",
                "error_code": e.code,
                "error_message": str(e.message),
                "signal": latest_signal,
                "bar_time": latest_bar_time,
            }
        if trade is not None:
            trade.setdefault("signal", latest_signal)
            trade.setdefault("bar_time", latest_bar_time)
            state["trades"].append(trade)

    # 3. 거래 후 Binance 잔고 재조회 (source of truth)
    base_qty, quote_qty = get_balances(client, base, quote)
    current_price = get_current_price(client, symbol)
    equity = quote_qty + base_qty * current_price

    state["cash"] = quote_qty
    state["position"]["qty"] = base_qty
    state["position"]["avg_cost"] = _compute_avg_cost(state["trades"], base_qty)

    state["history"].append({
        "time": now.isoformat(),
        "bar_time": latest_bar_time,
        "price": current_price,
        "signal": latest_signal,
        "position_value": base_qty * current_price,
        "cash": quote_qty,
        "equity": equity,
    })
    if equity > state["peak_equity"]:
        state["peak_equity"] = equity

    state["last_tick"] = now.isoformat()
    state["last_price"] = current_price
    state["last_signal"] = latest_signal
    state["last_bar_time"] = latest_bar_time
    state["mode"] = "testnet" if testnet else "mainnet"

    save_state(state_path, state)
    render_dashboard(state, dashboard_path)

    mode = "testnet" if testnet else "mainnet"
    result = {
        "trade": trade,
        "signal": latest_signal,
        "price": current_price,
        "equity": equity,
        "cash": quote_qty,
        "base_qty": base_qty,
        "bar_time": latest_bar_time,
        "duplicate_bar": already_processed,
        "mode": mode,
    }
    send_telegram_message(format_tick_notification(mode, result))
    return result
