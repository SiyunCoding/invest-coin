"""한 번의 Live (testnet/mainnet) trading tick.

- 가격 데이터: load_ohlcv (Binance 직접; testnet 모드에서도 캔들 조회는 mainnet 공개 API 사용)
- 신호 계산: cycle_aware 등 등록된 전략 그대로
- 매매 실행: Binance API 시장가 주문
- 잔고 / 가격: 매 tick마다 Binance에서 조회 (source of truth)
- 거래 로그 + history: state.json에 저장 (대시보드 + 텔레그램 알림용)

안전장치 (mainnet에서 특히 중요):
- daily_loss_limit_pct: 하루 손실이 자본의 이 %를 넘으면 자동 정지
- max_position_weight: 한 번에 사는 비율 상한
- max_signal_value: 신호가 이상하게 크면 무시 (전략 버그/데이터 오염 방지)
- halt 파일: ~/invest-coin/.halt 파일이 있으면 모든 매매 중지 (수동 비상정지)
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from binance.exceptions import BinanceAPIException

from ..common import load_state, render_dashboard, save_state
from ..data import load_ohlcv
from ..notifier import format_tick_notification, send_telegram_message
from ..strategies import REGISTRY
from .client import get_client
from .executor import (
    get_balances,
    get_current_price,
    rebalance_to_target,
    split_symbol,
)


# 안전장치 디폴트 — config에서 override 가능
DEFAULT_SAFETY = {
    "daily_loss_limit_pct": 0.05,   # 일일 -5% 도달 시 자동 정지
    "max_position_weight": 1.0,     # 신호를 이 비율로 클램프 (1.0 = 100% 허용)
    "max_signal_value": 1.0,        # 신호 > 이 값이면 이상 신호로 간주 → 무시
    "halt_file": ".halt",           # 이 파일 존재 시 모든 매매 중지
}


def _check_halt_file(root_dir: Path, halt_filename: str) -> bool:
    """halt 파일이 있으면 True. 수동 비상정지용."""
    return (root_dir / halt_filename).exists()


def _is_signal_anomalous(signal: float, max_val: float) -> bool:
    """신호가 비정상 범위면 True. NaN, 음수, 너무 큰 값 차단."""
    if signal != signal:  # NaN check
        return True
    if signal < 0 or signal > max_val:
        return True
    return False


def _today_str(now: datetime) -> str:
    """UTC 기준 YYYY-MM-DD 문자열."""
    return now.strftime("%Y-%m-%d")


def _check_daily_loss_limit(state: dict, current_equity: float, now: datetime,
                             loss_limit_pct: float) -> tuple[bool, dict]:
    """일일 손실이 한도 넘었는지 체크 + 일일 트래커 갱신.

    Returns: (halted, tracker_dict). halted=True면 매매 정지.
    """
    today = _today_str(now)
    tracker = state.get("daily_loss_tracker") or {}

    # 날짜 바뀌었으면 트래커 리셋
    if tracker.get("date") != today:
        tracker = {
            "date": today,
            "start_equity": current_equity,
            "halted_today": False,
        }

    if tracker.get("halted_today"):
        return True, tracker

    start_eq = float(tracker.get("start_equity", current_equity))
    if start_eq <= 0:
        return False, tracker

    pnl_pct = (current_equity - start_eq) / start_eq
    if pnl_pct <= -abs(loss_limit_pct):
        tracker["halted_today"] = True
        tracker["halted_at"] = now.isoformat()
        tracker["halted_at_equity"] = current_equity
        return True, tracker
    return False, tracker


def _init_live_state(config: dict, started_at: str, initial: float) -> dict:
    """state.json 초기 스키마. dashboard 모듈이 이 구조를 그대로 렌더링."""
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

    # 안전장치 설정 — config.safety로 override 가능
    safety = {**DEFAULT_SAFETY, **config.get("safety", {})}
    root_dir = Path(cache_dir).resolve().parent if isinstance(cache_dir, (str, Path)) else Path.cwd()

    # 0. Binance 현 상태 먼저 조회 (state 초기화 시 사용)
    base_qty, quote_qty = get_balances(client, base, quote)
    current_price = get_current_price(client, symbol)
    equity = quote_qty + base_qty * current_price

    state = load_state(state_path)
    # 모드 변경 (testnet ↔ mainnet) 감지 → 옛 state는 백업, fresh init.
    # 이유: testnet의 $88k 자산이 mainnet $100 자산과 섞이면 daily_loss_tracker가
    # 즉시 -99% 손실로 계산 → 첫 tick부터 halt 발동.
    current_mode = "testnet" if testnet else "mainnet"
    if state is not None and state.get("mode") not in (None, current_mode):
        old_mode = state.get("mode", "unknown")
        backup_path = state_path.with_name(
            f"{state_path.stem}_{old_mode}_{now.strftime('%Y%m%d_%H%M%S')}.json.bak"
        )
        save_state(backup_path, state)
        print(f"[live] mode change {old_mode} → {current_mode}, archived old state to {backup_path.name}")
        state = None
    if state is None:
        state = _init_live_state(config, now.isoformat(), equity)

    # 안전장치 1: 수동 비상정지 파일 체크
    halt_by_file = _check_halt_file(root_dir, safety["halt_file"])

    # 안전장치 2: 일일 손실 한도 체크
    halt_by_daily_loss, daily_tracker = _check_daily_loss_limit(
        state, equity, now, safety["daily_loss_limit_pct"]
    )
    state["daily_loss_tracker"] = daily_tracker

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
    raw_signal = float(signals.iloc[-1])
    latest_bar_time = ohlcv.index[-1].isoformat()

    # 안전장치 3: 신호 이상치 체크
    signal_anomalous = _is_signal_anomalous(raw_signal, safety["max_signal_value"])

    # 안전장치 4: 포지션 한도 클램프 (신호가 정상일 때만)
    latest_signal = raw_signal if not signal_anomalous else 0.0
    latest_signal = max(0.0, min(latest_signal, safety["max_position_weight"]))

    # 2. 같은 봉 두 번 처리 방지
    already_processed = state.get("last_bar_time") == latest_bar_time

    # 안전장치 통합 — 어떤 이유로든 halt면 매매 안 함
    halted_reasons = []
    if halt_by_file:
        halted_reasons.append(f"halt 파일 존재 ({safety['halt_file']})")
    if halt_by_daily_loss:
        loss_pct = safety["daily_loss_limit_pct"] * 100
        halted_reasons.append(f"일일 손실 한도 -{loss_pct:.1f}% 도달")
    if signal_anomalous:
        halted_reasons.append(f"이상 신호값 {raw_signal:.4f} (허용 [0, {safety['max_signal_value']}])")
    halted = bool(halted_reasons)

    trade = None
    if not already_processed and not halted:
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
    elif halted and not already_processed:
        # 안전장치 발동 — 거래 안 함 + state에 기록
        state["trades"].append({
            "time": now.isoformat(),
            "side": "halted",
            "reasons": halted_reasons,
            "signal": latest_signal,
            "raw_signal": raw_signal,
            "bar_time": latest_bar_time,
        })

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
        "raw_signal": raw_signal,
        "price": current_price,
        "equity": equity,
        "cash": quote_qty,
        "base_qty": base_qty,
        "bar_time": latest_bar_time,
        "duplicate_bar": already_processed,
        "mode": mode,
        "halted": halted,
        "halted_reasons": halted_reasons,
    }
    send_telegram_message(format_tick_notification(mode, result))
    return result
