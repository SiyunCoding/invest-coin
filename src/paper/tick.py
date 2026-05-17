"""한 번의 페이퍼 트레이딩 tick.

흐름:
  1. 상태 로드 (없으면 초기화)
  2. OHLCV 최신 데이터 fetch (미마감 봉은 자동 제외)
  3. 전략 신호 계산 (마지막 마감 봉 기준)
  4. 포트폴리오 리밸런싱
  5. 상태 + 히스토리 저장
  6. 대시보드 HTML 재생성

신호는 마지막 마감 봉에서 계산되어 즉시 적용된다 (backtest의 signal.shift(1) 과 동일하게,
'어제 정보로 오늘 포지션 결정').
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ..data import load_ohlcv
from ..notifier import format_tick_notification, send_telegram_message
from ..strategies import REGISTRY
from .dashboard import render_dashboard
from .portfolio import Portfolio
from .state import init_state, load_state, save_state


def run_tick(
    state_path: Path,
    dashboard_path: Path,
    config: dict,
    cache_dir: Path | str = "data",
) -> dict:
    """한 tick 실행. 결과 요약 dict 반환."""
    now = datetime.now(timezone.utc)

    state = load_state(state_path)
    if state is None:
        state = init_state(config, started_at=now.isoformat())

    ohlcv = load_ohlcv(
        symbol=config["symbol"],
        interval=config["interval"],
        lookback_days=config.get("lookback_days", 730),
        cache_dir=cache_dir,
    )
    if ohlcv.empty:
        raise RuntimeError(f"No data fetched for {config['symbol']}")

    meta = REGISTRY[config["strategy"]]
    strategy = meta.cls(**config.get("strategy_params", {}))
    signals = strategy.generate_signals(ohlcv)

    latest_signal = float(signals.iloc[-1])
    latest_price = float(ohlcv["close"].iloc[-1])
    latest_bar_time = ohlcv.index[-1].isoformat()

    portfolio = Portfolio(
        cash=state["cash"],
        qty=state["position"]["qty"],
        avg_cost=state["position"]["avg_cost"],
        fee_rate=config["fee_rate"],
        slippage_rate=config["slippage_rate"],
    )

    # 같은 봉을 두 번 처리하면 안 됨 (GHA 재실행 등)
    already_processed = state.get("last_bar_time") == latest_bar_time
    trade = None
    if not already_processed:
        trade = portfolio.rebalance(latest_signal, latest_price, now)
        if trade is not None:
            trade["signal"] = latest_signal
            trade["bar_time"] = latest_bar_time
            state["trades"].append(trade)

    state["cash"] = portfolio.cash
    state["position"]["qty"] = portfolio.qty
    state["position"]["avg_cost"] = portfolio.avg_cost

    equity = portfolio.mark_to_market(latest_price)
    state["history"].append({
        "time": now.isoformat(),
        "bar_time": latest_bar_time,
        "price": latest_price,
        "signal": latest_signal,
        "position_value": portfolio.qty * latest_price,
        "cash": portfolio.cash,
        "equity": equity,
    })
    if equity > state["peak_equity"]:
        state["peak_equity"] = equity

    state["last_tick"] = now.isoformat()
    state["last_price"] = latest_price
    state["last_signal"] = latest_signal
    state["last_bar_time"] = latest_bar_time

    save_state(state_path, state)
    render_dashboard(state, dashboard_path)

    result = {
        "trade": trade,
        "signal": latest_signal,
        "price": latest_price,
        "equity": equity,
        "cash": portfolio.cash,
        "base_qty": portfolio.qty,
        "bar_time": latest_bar_time,
        "duplicate_bar": already_processed,
    }
    send_telegram_message(format_tick_notification("paper", result))
    return result
