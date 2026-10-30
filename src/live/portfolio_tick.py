"""Trend Rotation 일일 tick (BTC 슬리브 + 월간 알트 유니버스, 현물 롱온리).

흐름:
  1. Binance 잔고/가격/거래규칙 조회 → 총자산 (source of truth)
  2. 외부 입출금 감지 (testnet 잔고 리셋 등) → 성과(NAV)에서 분리
  3. 가장 최근 월말 이후 선정된 적 없으면 유니버스 재선정 (월말 tick 을 놓쳐도 다음 tick 에 따라잡음)
  4. 마감 일봉으로 종목별 (frac, size) → 목표 비중 → 리밸런스 밴드
  5. 안전장치 → 매도 먼저, 매수 나중 → state / 대시보드 / Telegram

안전장치:
  - halt 파일: 모든 주문 중지 (수동 비상정지). 두 곳 중 하나라도 있으면 발동:
      · 저장소 루트의 .halt (git 에 커밋된 경우 — GitHub 웹에서 파일 추가로도 가능)
      · 서버 홈의 ~/.invest-coin.halt (러너 checkout 의 git clean 에 지워지지 않음)
  - 손실 한도: 직전 tick 대비 -daily_loss_limit_pct 이하면 매수만 막음 (청산/축소는 허용)
  - 이상 목표: NaN/음수/총합>1 이면 주문 중지
  - 같은 봉 재처리 방지 (last_bar_time), 오래된 데이터(기준 봉과 다른 마지막 봉) 종목 제외
  - 소액 계좌: 총자산 < min_equity_for_alts 면 알트 슬리브 끄고 BTC 단독 (히스테리시스 10%)
  - 주문 후 단계에서 예외가 나도 state(체결 기록 + 추적 종목)는 저장하고 다음 tick 에 재동기화
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from ..common import load_state, render_dashboard, save_state
from ..data import load_ohlcv
from ..notifier import format_portfolio_notification, send_telegram_message
from ..portfolio import (
    TrendRotationConfig, apply_band, is_eligible_symbol, select_universe, should_drop, target_weights,
)
from .client import get_client
from .portfolio_executor import get_free_balances, get_prices, load_exchange, rebalance_portfolio, snapshot

PUBLIC_API = "https://api.binance.com/api/v3"
STRATEGY = "trend_rotation"
DEFAULT_SAFETY = {
    "daily_loss_limit_pct": 0.05,
    "halt_file": ".halt",
}
HOME_HALT_FILE = Path.home() / ".invest-coin.halt"
MAX_RECORDS = 2000          # trades / history 보관 상한
DUST_USD = 1.0              # 이 미만 보유는 추적 안 함 (팔 수도 없는 먼지)


def _halt_requested(root_dir: Path, halt_file: str) -> str | None:
    """비상정지 파일 경로 (없으면 None). 러너 작업 폴더는 매 실행 git clean 되므로 홈 경로도 본다."""
    for path in (root_dir / halt_file, HOME_HALT_FILE):
        if path.exists():
            return str(path)
    return None


def _retry(fn, *args, tries: int = 3, wait: float = 2.0, **kwargs):
    for attempt in range(tries):
        try:
            return fn(*args, **kwargs)
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(wait * (attempt + 1))


# ---------------- 데이터 ----------------
def _candidate_symbols(pool: int) -> list[str]:
    """메인넷에서 거래 중인 적격 USDT 페어 중 24h 거래대금 상위 pool 개 (유니버스 후보)."""
    info = requests.get(f"{PUBLIC_API}/exchangeInfo", timeout=20).json()
    trading = {s["symbol"] for s in info["symbols"]
               if s.get("status") == "TRADING" and is_eligible_symbol(s["symbol"])}
    tickers = requests.get(f"{PUBLIC_API}/ticker/24hr", timeout=20).json()
    ranked = sorted((t for t in tickers if t["symbol"] in trading),
                    key=lambda t: float(t["quoteVolume"]), reverse=True)
    return [t["symbol"] for t in ranked[:pool]]


def _daily(symbol: str, cache_dir: Path, lookback_days: int) -> pd.DataFrame:
    """일봉 (Binance 만 — 라이브는 CryptoCompare 폴백 금지: 거래대금 단위가 달라 유니버스가 틀어짐)."""
    return load_ohlcv(symbol=symbol, interval="1d", lookback_days=lookback_days,
                      cache_dir=cache_dir, allow_fallback=False)


def last_month_end(bar_time: pd.Timestamp) -> pd.Timestamp:
    """bar_time 이 월말이면 그 날, 아니면 직전 월말 (UTC 00:00 봉 기준)."""
    if (bar_time + timedelta(days=1)).month != bar_time.month:
        return bar_time
    return bar_time.replace(day=1) - timedelta(days=1)


# ---------------- 상태 ----------------
def _init_state(config: dict, now: datetime, equity: float, btc_price: float, mode: str) -> dict:
    return {
        "strategy": STRATEGY,
        "mode": mode,
        "config": config,
        "started_at": now.isoformat(),
        "initial_equity": equity,
        "start_btc_price": btc_price,
        "nav": 1.0,            # 외부 입출금을 제외한 시간가중 수익 지수
        "peak_nav": 1.0,
        "external_flows": 0.0,
        "holdings": {},        # {symbol: qty} 직전 tick 종료 시점
        "cash": equity,
        "prev_fracs": {},
        "universe": {"symbols": [], "selected_at": None},
        "alts_enabled": None,
        "resync": False,
        "trades": [],
        "history": [],
        "last_tick": None,
        "last_bar_time": None,
    }


def _archive_if_incompatible(state: dict | None, state_path: Path, backup_dir: Path,
                             mode: str, now: datetime) -> dict | None:
    """전략/모드가 바뀌면 옛 state 백업 후 새로 시작 (자산 기준점이 섞이면 손실 한도 오작동)."""
    if state is None:
        return None
    if state.get("strategy") == STRATEGY and state.get("mode") == mode:
        return state
    old = f"{state.get('strategy', 'cycle_aware')}_{state.get('mode', 'unknown')}"
    backup = backup_dir / f"{state_path.stem}_{old}_{now.strftime('%Y%m%d_%H%M%S')}.json"
    save_state(backup, state)
    print(f"[live] state archived → {backup}")
    return None


def _external_flow(state: dict, prices: dict[str, float], equity: float) -> float:
    """직전 tick 보유분을 현재가로 평가한 값과 실제 자산의 차이 = 외부 입출금 추정.

    거래는 tick 안에서만 일어나므로 tick 사이의 차이는 가격 변화 또는 외부 유입뿐.
    """
    if state.get("last_tick") is None or state.get("resync"):
        return 0.0
    expected = float(state.get("cash", 0.0)) + sum(
        q * prices.get(s, 0.0) for s, q in state.get("holdings", {}).items()
    )
    diff = equity - expected
    return diff if abs(diff) > max(10.0, 0.005 * equity) else 0.0


def _alts_enabled(state: dict, equity: float, threshold: float) -> bool:
    """소액 경계 히스테리시스: 켜져 있었으면 90% 아래로 내려가야 끔 (경계에서 매일 전체 매매 방지)."""
    if state.get("alts_enabled"):
        return equity >= 0.9 * threshold
    return equity >= threshold


def _next_prev_fracs(state: dict, fracs: dict, desired: dict, weights: dict, skip_all: bool) -> dict:
    """체결로 목표에 실제 도달한 종목만 새 frac 을 기록 → 정지/실패/미체결 종목은 다음 tick 에 재시도."""
    prev = state.get("prev_fracs", {})
    if skip_all:
        return prev
    out = {}
    for sym, f in fracs.items():
        want, got = desired.get(sym, 0.0), weights.get(sym, 0.0)
        reached = abs(got - want) <= max(0.003, 0.25 * want)
        out[sym] = f if reached else prev.get(sym, 0.0)
    return out


def _trim(records: list) -> list:
    return records[-MAX_RECORDS:]


# ---------------- tick ----------------
def run_portfolio_tick(state_path: Path, dashboard_path: Path, config: dict,
                       cache_dir: Path | str = "data", root_dir: Path | None = None,
                       backup_dir: Path | None = None) -> dict:
    now = datetime.now(timezone.utc)
    testnet = bool(config.get("testnet", True))
    mode = "testnet" if testnet else "mainnet"
    cache_dir = Path(cache_dir)
    root_dir = Path(root_dir) if root_dir else cache_dir.resolve().parent
    backup_dir = Path(backup_dir) if backup_dir else state_path.parent
    safety = {**DEFAULT_SAFETY, **config.get("safety", {})}
    cfg = TrendRotationConfig.from_dict(config.get("trend_rotation"))
    lookback = int(config.get("lookback_days", 1000))
    if lookback < 2 * max(cfg.lookbacks):
        raise ValueError(f"lookback_days({lookback}) 는 최장 Donchian 기간의 2배 이상이어야 함 (경로의존 수렴)")
    client = get_client(testnet=testnet)

    # 1) 계정 현황 (주문 전)
    tradable, rules = _retry(load_exchange, client)
    balances = _retry(get_free_balances, client)
    prices = _retry(get_prices, client)

    state = _archive_if_incompatible(load_state(state_path), state_path, backup_dir, mode, now)
    prev_tracked = {cfg.btc_symbol} | set((state or {}).get("holdings", {}))
    prev_tracked |= set((state or {}).get("universe", {}).get("symbols", []))
    equity_prev_scope, _, _ = snapshot(balances, prices, prev_tracked & set(prices))
    if state is None:
        state = _init_state(config, now, equity_prev_scope, prices.get(cfg.btc_symbol, 0.0), mode)

    # 2) 외부 입출금 분리 → 시간가중 NAV (직전 tick 이후 구간)
    resync = bool(state.get("resync"))
    flow = _external_flow(state, prices, equity_prev_scope)
    prev_equity = state["history"][-1]["equity"] if state["history"] else equity_prev_scope
    if prev_equity > 0 and state["history"] and not resync:
        state["nav"] *= (equity_prev_scope - flow) / prev_equity
    state["external_flows"] = float(state.get("external_flows", 0.0)) + flow

    # 3) 소액 계좌 → BTC 단독
    alts_enabled = _alts_enabled(state, equity_prev_scope, float(config.get("min_equity_for_alts", 3000)))
    state["alts_enabled"] = alts_enabled
    if not alts_enabled:
        cfg.btc_sleeve, cfg.alt_slots = 1.0, 0

    # 4) 기준 봉 + 유니버스
    btc_df = _retry(_daily, cfg.btc_symbol, cache_dir, lookback)
    if btc_df.empty:
        raise RuntimeError("BTC 일봉 데이터 없음 — 주문하지 않고 중단")
    bar_time = btc_df.index[-1]
    if now - bar_time.to_pydatetime() > timedelta(days=2):
        raise RuntimeError(f"BTC 마지막 봉 {bar_time} 이 오래됨 — 데이터 이상, 주문하지 않고 중단")

    uni = state.get("universe", {})
    selected_at = pd.Timestamp(uni["selected_at"]) if uni.get("selected_at") else None
    if alts_enabled and (selected_at is None or selected_at < last_month_end(bar_time)):
        cands = {}
        for s in _retry(_candidate_symbols, int(config.get("candidate_pool", 40))):
            try:
                cands[s] = _retry(_daily, s, cache_dir, lookback)
            except Exception as e:  # 후보 하나 실패가 재선정 전체를 막지 않게
                print(f"[live] candidate {s} skipped: {e}")
        uni = {"symbols": select_universe(cands, cfg.alt_slots, cfg.min_listing_days, cfg.min_median_volume),
               "selected_at": bar_time.isoformat()}
        state["universe"] = uni
    universe = uni.get("symbols", []) if alts_enabled else []

    # 재선정 후 추적 범위로 다시 평가 (새 유니버스 종목을 이미 들고 있을 수 있음)
    tracked = prev_tracked | set(universe)
    equity_pre, _, current = snapshot(balances, prices, tracked & set(prices))

    closes = {cfg.btc_symbol: btc_df["close"]}
    live_universe, dropped, untradable, fetch_failed = [], [], [], []
    for s in universe:
        try:
            df = btc_df if s == cfg.btc_symbol else _retry(_daily, s, cache_dir, lookback)
        except Exception as e:
            print(f"[live] {s} data fetch failed: {e}")
            fetch_failed.append(s)
            continue
        if df.empty or df.index[-1] != bar_time or should_drop(df, cfg.exit_median_volume, cfg.min_median_move):
            dropped.append(s)  # 상장폐지/데이터 끊김/유동성 고갈 → 보유분은 청산
            continue
        if s not in tradable:  # testnet 은 거래 가능 페어가 적음
            untradable.append(s)
            continue
        closes[s] = df["close"]
        live_universe.append(s)

    # 5) 목표 비중 + 밴드
    targets, fracs = target_weights(closes, live_universe, cfg)
    desired = apply_band(targets, current, fracs, state.get("prev_fracs", {}), live_universe, cfg)
    for s in fetch_failed:  # 일시적 데이터 실패 종목은 팔지 않고 현 상태 유지
        desired[s] = current.get(s, 0.0)
    desired = {s: w for s, w in desired.items() if s in tradable}

    # 6) 안전장치
    reasons, buy_block = [], []
    halt_path = _halt_requested(root_dir, safety["halt_file"])
    if halt_path:
        reasons.append(f"halt 파일 존재 ({halt_path})")
    if any(math.isnan(w) or w < 0 for w in targets.values()) or sum(targets.values()) > 1.0 + 1e-6:
        reasons.append(f"이상 목표 비중 {targets}")
    if state["history"] and prev_equity > 0 and not resync:
        change = (equity_prev_scope - flow) / prev_equity - 1
        if change <= -abs(safety["daily_loss_limit_pct"]):
            buy_block.append(f"직전 tick 대비 {change*100:.1f}% (한도 -{safety['daily_loss_limit_pct']*100:.0f}%) → 매수 중지")
    duplicate = state.get("last_bar_time") == bar_time.isoformat()

    # 7) 주문
    trades = []
    if not duplicate and not reasons:
        trades = rebalance_portfolio(client, desired, tracked | set(desired), rules, allow_buys=not buy_block)
        for t in trades:
            t["bar_time"] = bar_time.isoformat()
        state["trades"].extend(trades)
    if (reasons or buy_block) and not duplicate:
        state["trades"].append({"time": now.isoformat(), "side": "halted", "reasons": reasons + buy_block,
                                "bar_time": bar_time.isoformat()})

    # 8) 사후 잔고 → state (실패해도 체결 기록과 추적 종목은 남겨 다음 tick 이 재동기화)
    try:
        balances = _retry(get_free_balances, client)
        prices = _retry(get_prices, client)
    except Exception:
        state["holdings"] = {**{s: 0.0 for s in tracked | set(desired)}, **state.get("holdings", {})}
        state["universe"] = uni
        state["resync"] = True
        state["trades"] = _trim(state["trades"])
        save_state(state_path, state)
        raise
    equity, qty, weights = snapshot(balances, prices, (tracked | set(desired)) & set(prices))
    if equity_pre > 0 and not resync:
        state["nav"] *= equity / equity_pre  # tick 안의 수수료/체결 손실 반영
    state["resync"] = False
    state["holdings"] = {s: q for s, q in qty.items() if q * prices.get(s, 0.0) >= DUST_USD}
    state["cash"] = balances.get("USDT", 0.0)
    if not duplicate:
        state["prev_fracs"] = _next_prev_fracs(state, fracs, desired, weights, skip_all=bool(reasons or buy_block))
    state["peak_nav"] = max(state.get("peak_nav", 1.0), state["nav"])
    btc_px = prices.get(cfg.btc_symbol, 0.0)
    state["history"].append({
        "time": now.isoformat(), "bar_time": bar_time.isoformat(), "equity": equity,
        "cash": state["cash"], "exposure": sum(weights.values()), "nav": state["nav"],
        "external_flow": flow, "btc_price": btc_px,
        "weights": {s: round(w, 4) for s, w in weights.items() if w > 0.0005},
    })
    state["history"] = _trim(state["history"])
    state["trades"] = _trim(state["trades"])
    state["last_tick"] = now.isoformat()
    state["last_bar_time"] = bar_time.isoformat()
    state["targets"] = {s: round(w, 4) for s, w in targets.items()}
    state["fracs"] = {s: round(f, 3) for s, f in fracs.items()}
    save_state(state_path, state)
    render_dashboard(state, dashboard_path)

    result = {
        "mode": mode, "bar_time": bar_time.isoformat(), "equity": equity, "cash": state["cash"],
        "exposure": sum(weights.values()), "weights": weights, "targets": targets, "fracs": fracs,
        "trades": trades, "universe": live_universe, "dropped": dropped, "untradable": untradable,
        "fetch_failed": fetch_failed,
        "halted": bool(reasons), "buy_blocked": bool(buy_block), "reasons": reasons + buy_block,
        "duplicate_bar": duplicate, "external_flow": flow, "nav": state["nav"],
        "alts_enabled": alts_enabled,
        "btc_return": (btc_px / state["start_btc_price"] - 1) if state.get("start_btc_price") else 0.0,
    }
    send_telegram_message(format_portfolio_notification(result))
    return result
