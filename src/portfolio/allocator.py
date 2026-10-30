"""Trend Rotation 목표 비중 계산 + 리밸런스 밴드.

구성 (2026-10 전략 검증 결과, tasks/lessons.md L12 참고):
  - BTC 슬리브 (btc_sleeve, 기본 50%): BTC Donchian 앙상블 × min(btc_target_vol/σ90, 1)
  - 알트 슬리브 (나머지): 월간 유니버스 상위 alt_slots 개, 종목당 1/alt_slots,
    각 종목 Donchian 앙상블 × min(alt_target_vol/σ90, 1)   (BTC 가 유니버스에 들면 BTC 비중에 합산)
  - 리밸런스: 추세 신호(frac) 변화 → 즉시. 변동성 때문만의 변화 → 슬롯 대비 rebalance_threshold 초과 시.

백테스트(research/backtest_trend_rotation.py)와 라이브(src/live/portfolio_tick.py)가 같은 함수를 쓴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .signals import DEFAULT_LOOKBACKS, trend_fraction, vol_scale


@dataclass
class TrendRotationConfig:
    btc_symbol: str = "BTCUSDT"
    btc_sleeve: float = 0.5
    btc_target_vol: float = 0.40
    alt_slots: int = 10
    alt_target_vol: float = 0.60
    vol_window: int = 90
    lookbacks: tuple[int, ...] = field(default=DEFAULT_LOOKBACKS)
    rebalance_threshold: float = 0.20
    # 유니버스 (Zarattini 7.1)
    min_listing_days: int = 365
    min_median_volume: float = 2e6
    exit_median_volume: float = 1e6
    min_median_move: float = 0.005

    @classmethod
    def from_dict(cls, d: dict | None) -> "TrendRotationConfig":
        d = dict(d or {})
        if "lookbacks" in d:
            d["lookbacks"] = tuple(int(x) for x in d["lookbacks"])
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    @property
    def alt_slot_weight(self) -> float:
        return (1.0 - self.btc_sleeve) / self.alt_slots if self.alt_slots > 0 else 0.0


def latest_signal(close: pd.Series, target_vol: float, cfg: TrendRotationConfig) -> tuple[float, float]:
    """마지막 마감 봉 기준 (frac, size)."""
    frac = trend_fraction(close, cfg.lookbacks)
    size = vol_scale(close, target_vol, cfg.vol_window)
    if frac.empty:
        return 0.0, 0.0
    return float(frac.iloc[-1]), float(size.reindex(frac.index).iloc[-1])


def target_weights(
    closes: dict[str, pd.Series],
    universe: list[str],
    cfg: TrendRotationConfig,
) -> tuple[dict[str, float], dict[str, float]]:
    """종목별 목표 비중(총자산 대비)과 추세 비율(frac).

    closes: {symbol: 종가 Series (마감 봉까지)}. universe: 알트 슬리브 종목 목록.
    """
    btc = cfg.btc_symbol
    btc_sig = None
    if cfg.btc_sleeve > 0 and btc in closes:
        btc_sig = latest_signal(closes[btc], cfg.btc_target_vol, cfg)
    alt_sigs = {
        sym: latest_signal(closes[sym], cfg.alt_target_vol, cfg)
        for sym in universe if sym in closes
    }
    return weights_from_signals(btc_sig, alt_sigs, cfg)


def weights_from_signals(
    btc_sig: tuple[float, float] | None,
    alt_sigs: dict[str, tuple[float, float]],
    cfg: TrendRotationConfig,
) -> tuple[dict[str, float], dict[str, float]]:
    """(frac, size) 신호 → 종목별 총자산 대비 비중. 백테스트도 이 함수를 직접 호출."""
    weights: dict[str, float] = {}
    fracs: dict[str, float] = {}
    if btc_sig is not None:
        f, s = btc_sig
        fracs[cfg.btc_symbol] = f
        weights[cfg.btc_symbol] = cfg.btc_sleeve * f * s

    slot = cfg.alt_slot_weight
    for sym, (f, s) in alt_sigs.items():
        if slot <= 0:
            break
        fracs[sym] = f
        weights[sym] = weights.get(sym, 0.0) + slot * f * s

    total = sum(weights.values())
    if total > 1.0:  # 현물: 총 노출 100% 상한
        weights = {k: v / total for k, v in weights.items()}
    return weights, fracs


def slot_cap(symbol: str, universe: list[str], cfg: TrendRotationConfig) -> float:
    """그 종목에 배정 가능한 최대 비중 (밴드 기준 크기)."""
    cap = 0.0
    if symbol == cfg.btc_symbol:
        cap += cfg.btc_sleeve
    if symbol in universe:
        cap += cfg.alt_slot_weight
    return cap if cap > 0 else cfg.alt_slot_weight


def apply_band(
    targets: dict[str, float],
    current: dict[str, float],
    fracs: dict[str, float],
    prev_fracs: dict[str, float],
    universe: list[str],
    cfg: TrendRotationConfig,
) -> dict[str, float]:
    """밴드 적용 후 실제로 맞출 비중.

    - frac 이 바뀌었거나(진입/청산) 목표가 0 이면 → 목표로 즉시 이동
    - 아니면 |목표-현재| > threshold × max(현재, 슬롯 크기) 일 때만 이동
    - 목표 목록에 없는 보유 종목 → 0 (유니버스 탈락/청산)
    """
    out: dict[str, float] = {}
    for sym in set(targets) | set(current):
        tgt = targets.get(sym, 0.0)
        cur = current.get(sym, 0.0)
        signal_changed = abs(fracs.get(sym, 0.0) - prev_fracs.get(sym, 0.0)) > 1e-9
        if signal_changed or tgt == 0.0:
            out[sym] = tgt
        elif abs(tgt - cur) > cfg.rebalance_threshold * max(cur, slot_cap(sym, universe, cfg)):
            out[sym] = tgt
        else:
            out[sym] = cur
    return out
