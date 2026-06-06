"""한 번의 Futures Scalping Tick (멀티 코인 50x SHORT on RSI 5m > threshold).

흐름:
  1. Binance Futures exchange_info → 모든 USDT 무기한 선물 심볼 자동 수집
  2. 포지션 + mark price 한 방에 조회 (코인별로 안 돌림)
  3. 각 심볼:
     a. 5분봉 → RSI(14) 계산
     b. 포지션 있으면: 기다림 (TP 서버에서 자동 처리)
     c. 포지션 없으면:
        - 직전에 포지션 있었으면 closure 감지 (TP 체결 or 청산)
        - RSI > threshold → 진입 + TP 자동 청산 주문
  4. 알림 정책 (텔레그램 폭탄 방지):
     - 진입 / 청산 / 에러 → 즉시 알림 (코인별)
     - 일반 idle → 알림 안 보냄
     - 1시간마다 1번 헬스체크 요약 알림 (heartbeat_every_n_ticks)

설계:
  - source of truth = Binance (포지션은 매 tick 재조회)
  - 손절 없음 (Binance가 −100% 마진에서 자동 청산)
  - 익절은 TAKE_PROFIT_MARKET 서버 사이드 주문
  - 동시 포지션 허용 (코인마다 독립)
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
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
    get_all_mark_prices,
    get_all_positions,
    get_available_balance,
    get_max_leverage_map,
    list_usdt_perpetuals,
    open_short_with_tp,
)

# Binance API rate-limit 여유: klines 호출은 가중치 1, 분당 2400 한도라
# 100개 심볼 × 1콜 = 100 weight per tick, 5분당이라 충분히 안전.
# 다만 너무 빨리 던지면 burst limit 걸릴 수 있어서 50ms slot.
_KLINES_SLEEP_SEC = 0.05


def _init_state(config: dict, started_at: str, initial_balance: float) -> dict:
    return {
        "config": config,
        "initial_balance": initial_balance,
        "trades": [],  # 모든 거래 이력 (entry/closure/error), 각각 symbol 포함
        "history": [],  # tick별 요약 (요즘은 짧게 보관)
        "peak_balance": initial_balance,
        "started_at": started_at,
        "last_tick": None,
        "tick_count": 0,
        "positions": {},  # {symbol: {qty, entry_price, tp_stop_price, entered_at}}
        "leverage_initialized": {},  # {symbol: true}
        "mode": "futures-demo" if config.get("demo", True) else "futures-mainnet",
    }


def _fetch_rsi_5m(client, symbol: str, period: int = 14, limit: int = 100) -> float:
    """선물 5분봉 받아서 마지막 RSI 값. 미마감 봉 제외."""
    klines = client.futures_klines(symbol=symbol, interval="5m", limit=limit)
    closes = pd.Series([float(k[4]) for k in klines])
    close_times = [int(k[6]) for k in klines]
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if close_times and close_times[-1] > now_ms:
        closes = closes.iloc[:-1]
    if len(closes) < period + 5:
        return float("nan")
    rsi = wilder_rsi(closes, period=period)
    return float(rsi.iloc[-1])


def _kst_str(dt: datetime | None = None) -> str:
    if dt is None:
        dt = datetime.now(timezone.utc)
    kst = dt.astimezone(timezone(timedelta(hours=9)))
    return kst.strftime("%Y-%m-%d %H:%M KST")


def _format_entry(mode: str, symbol: str, result: dict, rsi: float, leverage: int) -> str:
    drop_pct = (result["entry_price"] - result["tp_stop_price"]) / result["entry_price"] * 100
    return "\n".join([
        f"📉 *SHORT 진입* · `{symbol}`",
        f"• 마진: `${result['margin_usdt']:.0f}` × `{leverage}x`",
        f"• 진입가: `${result['entry_price']:,.4f}` · RSI `{rsi:.1f}`",
        f"• 🎯 TP `${result['tp_stop_price']:,.4f}` (−{drop_pct:.2f}%) → `+${result['expected_net_profit']:.2f}`",
    ])


def _format_closure(mode: str, symbol: str, prev_pos: dict, balance_delta: float) -> str:
    """포지션이 사라졌을 때 (TP 체결 또는 청산). 잔고 변화로 추정."""
    if balance_delta > 0.5:
        emoji, label = "✅", "TP 체결"
    elif balance_delta < -1.0:
        emoji, label = "💀", "청산"
    else:
        emoji, label = "🔄", "포지션 정리"
    return f"{emoji} *{label}* · `{symbol}` · `${balance_delta:+,.2f}`"


def _format_error(mode: str, symbol: str, code, message: str) -> str:
    # 너무 긴 메시지는 자름
    short_msg = str(message)[:120]
    return f"⚠️ `{symbol}` 진입 실패 (`{code}`) {short_msg}"


def _format_heartbeat(
    mode: str,
    balance: float,
    initial_balance: float,
    positions: dict,
    candidates: list[tuple[str, float]],
    total_symbols: int,
    tick_count: int,
    trade_summary: dict,
    leverage_range: tuple[int, int] = (50, 75),
) -> str:
    pnl = balance - initial_balance
    pnl_pct = (pnl / initial_balance * 100) if initial_balance > 0 else 0.0
    lines = [
        f"📊 *헬스체크* · tick #{tick_count}",
        f"💼 `${balance:,.2f}` (`{pnl:+,.2f}` / `{pnl_pct:+.2f}%`)",
        f"📈 추적 `{total_symbols}` · 오픈 `{len(positions)}` · RSI↑ `{len(candidates)}`",
        f"🧾 entries `{trade_summary.get('entries', 0)}` / closes `{trade_summary.get('closes', 0)}` / errors `{trade_summary.get('errors', 0)}`",
    ]
    if positions:
        lines.append("")
        for sym, p in list(positions.items())[:8]:
            lines.append(f"  📦 `{sym}` @ `${p['entry_price']:,.4f}`")
        if len(positions) > 8:
            lines.append(f"  ...외 {len(positions) - 8}개")
    if candidates:
        lines.append("")
        top = sorted(candidates, key=lambda x: -x[1])[:5]
        cand_str = " · ".join(f"`{s}`(`{r:.1f}`)" for s, r in top)
        lines.append(f"  🔥 후보: {cand_str}")
    return "\n".join(lines)


def _count_trades_by_type(trades: list) -> dict:
    out = {"entries": 0, "closes": 0, "errors": 0}
    for t in trades:
        tp = t.get("type", "")
        if tp == "entry":
            out["entries"] += 1
        elif tp == "closure":
            out["closes"] += 1
        elif tp == "error":
            out["errors"] += 1
    return out


def run_futures_tick(state_path: Path, config: dict) -> dict:
    """멀티 심볼 Futures scalping tick 한 번."""
    now = datetime.now(timezone.utc)
    demo = bool(config.get("demo", True))
    # 레버리지 범위 필터: 코인 max 레버리지가 [leverage_min, leverage_max] 안인 것만 진입
    # 실제 사용 = 코인의 max (범위 안에서). 옛 'leverage' 키도 폴백 지원.
    leverage_min = int(config.get("leverage_min", config.get("leverage", 50)))
    leverage_max = int(config.get("leverage_max", config.get("leverage", 50)))
    margin_usdt = float(config["margin_usdt"])
    tp_profit_pct = float(config["tp_profit_pct"])
    cushion_usdt = float(config.get("cushion_usdt", 2.0))
    rsi_threshold = float(config.get("rsi_threshold", 80.0))
    rsi_period = int(config.get("rsi_period", 14))
    heartbeat_every = int(config.get("heartbeat_every_n_ticks", 12))  # 12 × 5분 = 1시간
    exclude_symbols = list(config.get("exclude_symbols", []))
    explicit_symbols = list(config.get("symbols", []))  # 비어있으면 자동 수집

    client = get_futures_client(demo=demo)
    mode = "futures-demo" if demo else "futures-mainnet"

    # State (없거나 옛 단일심볼 스키마면 새로 초기화)
    state = load_state(state_path)
    if state is None or "positions" not in state or "leverage_initialized" not in state:
        balance0 = get_available_balance(client, "USDT")
        state = _init_state(config, now.isoformat(), balance0)

    # 1) 심볼 리스트 + 최대 레버리지 (cache: 1시간마다 갱신)
    last_symbols_fetch = state.get("last_symbols_fetch_ts", 0)
    symbols_cache = state.get("symbols_cache", [])
    max_lev_cache = state.get("max_leverage_map", {})
    need_refresh = (
        not symbols_cache or not max_lev_cache
        or (time.time() - last_symbols_fetch) > 3600
    )
    runtime_blacklist = set(state.get("runtime_blacklist", []))
    if need_refresh:
        all_symbols = (
            explicit_symbols if explicit_symbols
            else list_usdt_perpetuals(client, exclude=exclude_symbols)
        )
        max_lev_cache = get_max_leverage_map(client)
        # 레버리지 범위 필터 + 런타임 블랙리스트 (이전에 -1121/-4005 거부된 종목)
        symbols = [
            s for s in all_symbols
            if leverage_min <= max_lev_cache.get(s, 0) <= leverage_max
            and s not in runtime_blacklist
        ]
        state["symbols_cache"] = symbols
        state["max_leverage_map"] = max_lev_cache
        state["last_symbols_fetch_ts"] = time.time()
        state["leverage_filter"] = {"min": leverage_min, "max": leverage_max}
    else:
        symbols = [s for s in symbols_cache if s not in runtime_blacklist]

    # 2) 잔고 + 전체 포지션 + 전체 mark price (총 3콜)
    balance_before = get_available_balance(client, "USDT")
    positions_map = get_all_positions(client)  # {symbol: positionAmt}
    marks_map = get_all_mark_prices(client)    # {symbol: markPrice}

    # 3) 심볼 루프
    new_entries = []
    closures = []
    errors = []
    rsi_candidates = []  # RSI > threshold이지만 아직 진입 안 된 (자본 부족 등) 목록

    for symbol in symbols:
        try:
            pos_amt = positions_map.get(symbol, 0.0)
            has_position = abs(pos_amt) > 1e-9
            mark_price = marks_map.get(symbol)
            if mark_price is None:
                continue

            # 포지션 있는 심볼: idle 처리만
            if has_position:
                continue

            # 포지션 없는 심볼: 직전에 있었으면 closure, RSI 보고 진입 판단
            prev_pos = state["positions"].get(symbol)
            if prev_pos is not None:
                # 포지션 사라졌음 → closure
                closures.append({"symbol": symbol, "prev_pos": prev_pos})
                state["positions"].pop(symbol, None)
                state["trades"].append({
                    "time": now.isoformat(),
                    "type": "closure",
                    "symbol": symbol,
                    "entry_price": prev_pos["entry_price"],
                    "tp_stop_price": prev_pos.get("tp_stop_price"),
                })

            # RSI 계산
            rsi = _fetch_rsi_5m(client, symbol, period=rsi_period)
            if pd.isna(rsi):
                continue

            if rsi <= rsi_threshold:
                continue

            # RSI > threshold → 진입 시도
            rsi_candidates.append((symbol, rsi))

            # 자본 가드: 마진 충분히 남았는지
            if balance_before < margin_usdt * 1.5:
                continue

            # 필터 통과한 코인이라 max가 [leverage_min, leverage_max] 안에 있음.
            # 그 max 그대로 사용 (가장 공격적).
            effective_lev = int(max_lev_cache.get(symbol, leverage_min))

            # 레버리지/마진 모드 1회 설정 (clamped 값 사용)
            if not state["leverage_initialized"].get(symbol):
                try:
                    ensure_leverage_and_margin(
                        client, symbol, effective_lev,
                        margin_type=config.get("margin_type", "CROSSED")
                    )
                    state["leverage_initialized"][symbol] = True
                except BinanceAPIException as e:
                    errors.append({"symbol": symbol, "code": e.code, "message": str(e.message)})
                    state["trades"].append({
                        "time": now.isoformat(), "type": "error", "symbol": symbol,
                        "error_code": e.code, "error_message": str(e.message),
                        "stage": "leverage", "attempted_leverage": effective_lev,
                    })
                    continue

            # 묵은 TP 주문 청소
            try:
                cancel_all_open_orders(client, symbol)
            except BinanceAPIException:
                pass

            # 진입
            try:
                result = open_short_with_tp(
                    client, symbol=symbol,
                    margin_usdt=margin_usdt, leverage=effective_lev,
                    tp_profit_pct=tp_profit_pct, cushion_usdt=cushion_usdt,
                )
            except (BinanceAPIException, ValueError) as e:
                code = getattr(e, "code", "VALUE_ERROR")
                msg = getattr(e, "message", str(e))
                # 영구 거부될 심볼 자동 블랙리스트:
                # -1121 Invalid symbol (가짜/테스트 종목)
                # -4005 Quantity > max (저단가 코인)
                # -1109 Invalid account (특정 심볼이 demo 계정에 미허용)
                if code in (-1121, -4005, -1109):
                    runtime_blacklist = state.setdefault("runtime_blacklist", [])
                    if symbol not in runtime_blacklist:
                        runtime_blacklist.append(symbol)
                    if symbol in state.get("symbols_cache", []):
                        state["symbols_cache"].remove(symbol)
                errors.append({"symbol": symbol, "code": code, "message": str(msg)})
                state["trades"].append({
                    "time": now.isoformat(), "type": "error", "symbol": symbol,
                    "error_code": code, "error_message": str(msg),
                    "stage": "open_short", "rsi": rsi,
                })
                continue

            new_entries.append({"symbol": symbol, "result": result, "rsi": rsi, "leverage": effective_lev})
            state["positions"][symbol] = {
                "qty": result["qty"],
                "entry_price": result["entry_price"],
                "tp_stop_price": result["tp_stop_price"],
                "entered_at": now.isoformat(),
            }
            state["trades"].append({
                "time": now.isoformat(),
                "type": "entry",
                "symbol": symbol,
                "side": "SHORT",
                "qty": result["qty"],
                "entry_price": result["entry_price"],
                "tp_stop_price": result["tp_stop_price"],
                "leverage": effective_lev,
                "margin_usdt": margin_usdt,
                "notional": result["notional"],
                "rsi": rsi,
                "entry_order_id": result["entry"].get("orderId"),
                "tp_order_id": result["tp"].get("orderId"),
            })

            # 잔고 즉시 갱신 (자본 가드용)
            balance_before -= margin_usdt

            # 너무 빨리 던지면 rate limit
            time.sleep(_KLINES_SLEEP_SEC)
        except Exception as e:
            errors.append({"symbol": symbol, "code": "EXCEPTION", "message": str(e)})

    # 4) 잔고 재조회 (closure 잔고 변화 추정용)
    balance_after = get_available_balance(client, "USDT")

    # 5) 알림 발송
    for entry in new_entries:
        send_telegram_message(_format_entry(mode, entry["symbol"], entry["result"], entry["rsi"], entry["leverage"]))

    for closure in closures:
        # closure 시 잔고 변화는 (closure 1건 가정) 단순 추정 — 여러 closure 동시면 분배 불가, 합쳐서 표시
        delta = (balance_after - balance_before) / max(1, len(closures))
        send_telegram_message(_format_closure(mode, closure["symbol"], closure["prev_pos"], delta))

    for err in errors:
        send_telegram_message(_format_error(mode, err["symbol"], err["code"], err["message"]))

    state["tick_count"] = state.get("tick_count", 0) + 1
    state["last_tick"] = now.isoformat()
    if balance_after > state.get("peak_balance", 0):
        state["peak_balance"] = balance_after

    # Heartbeat (첫 tick에도 1번 보내 — 시작 직후 잘 도는지 즉시 확인 가능)
    if state["tick_count"] == 1 or state["tick_count"] % heartbeat_every == 0:
        trade_summary = _count_trades_by_type(state["trades"])
        send_telegram_message(_format_heartbeat(
            mode=mode,
            balance=balance_after,
            initial_balance=state["initial_balance"],
            positions=state["positions"],
            candidates=rsi_candidates,
            total_symbols=len(symbols),
            tick_count=state["tick_count"],
            trade_summary=trade_summary,
            leverage_range=(leverage_min, leverage_max),
        ))

    # 히스토리는 짧게 보관 (최근 24시간 = 288개)
    state["history"].append({
        "time": now.isoformat(),
        "balance": balance_after,
        "open_positions": len(state["positions"]),
        "rsi_candidates": len(rsi_candidates),
        "new_entries": len(new_entries),
        "closures": len(closures),
        "errors": len(errors),
    })
    if len(state["history"]) > 1000:
        state["history"] = state["history"][-1000:]

    save_state(state_path, state)

    return {
        "tick_count": state["tick_count"],
        "balance": balance_after,
        "open_positions": len(state["positions"]),
        "total_symbols": len(symbols),
        "new_entries": len(new_entries),
        "closures": len(closures),
        "errors": len(errors),
        "rsi_candidates": len(rsi_candidates),
        "mode": mode,
    }
