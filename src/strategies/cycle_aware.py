"""Cycle-Aware Adaptive Ensemble — 비트코인 반감기 사이클 + 가격 regime 결합.

설계 (세 가지 차원 결합):
1. **Price regime weight (메인 게이트)**:
   - ADX 기반 soft weighting: w_trend = clip((ADX - adx_lo) / (adx_hi - adx_lo), 0, 1)
   - SMA200 아래면 강제 평균회귀 모드 (w_trend = 0)
   - 추세장에서 Donchian-ATR, 횡보장에서 CRSI 자동 가중

2. **Cycle risk multiplier (보조)**:
   - months_since_last_halving으로 사이클 단계 분류
   - Accumulation (0~6m, 24~30m): 1.0   - Markup (6~18m): 1.2   ← 강세장 부스터
   - Distribution (18~24m): 0.7         ← 정점 근방 위험 회피
   - Markdown (30~42m): 0.5             ← 베어마켓 자본 보전
   - 반감기 날짜는 BTC 프로토콜 결정 → future leak 없음

3. **Vol-targeting (사이즈)**:
   - 변동성 폭증기 자동 deleverage (Moskowitz 2012)
   - ATR percentile > 90 추가 위험 회피 (size × 0.5)

학술 근거:
- Springer Comp Econ 2026: regime-conditioned 앙상블 Sharpe 1.01, MDD -19%
- Moskowitz/Ooi/Pedersen 2012: Vol-targeting이 TSMOM 알파의 대부분
- Quantpedia 2024: ADX 필터 + Donchian-ATR/MR 결합 검증
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..utils.indicators import adx, atr, realized_vol
from .base import Signal, Strategy
from .crsi import ConnorsRSI
from .donchian_atr import DonchianATR


# BTC 반감기 날짜 (UTC). 마지막은 추정.
HALVING_DATES_UTC = pd.to_datetime([
    "2012-11-28", "2016-07-09", "2020-05-11",
    "2024-04-20", "2028-04-15",
], utc=True)


def _months_since_last_halving(dates: pd.DatetimeIndex) -> pd.Series:
    """각 시점에서 가장 최근 반감기로부터 경과 개월수 (음수면 다음 반감기 이전).

    future leak 없음 — 반감기 날짜는 BTC 프로토콜에 사전 결정됨.
    """
    out = np.full(len(dates), np.nan)
    halvings = HALVING_DATES_UTC.to_numpy()
    dates_np = dates.to_numpy()
    for i, d in enumerate(dates_np):
        passed = halvings[halvings <= d]
        if len(passed) > 0:
            delta_days = (d - passed[-1]) / np.timedelta64(1, "D")
            out[i] = delta_days / 30.4375
    return pd.Series(out, index=dates, name="months_since_halving")


def _phase_multiplier(months: pd.Series, mult_markup: float, mult_dist: float,
                     mult_markdown: float) -> pd.Series:
    """months → phase multiplier."""
    m = months.to_numpy()
    out = np.ones(len(m), dtype=float)
    # Accumulation: 0~6 또는 24~30 (다음 반감기 전 6개월) → 1.0
    # Markup: 6~18 → mult_markup
    out[(m >= 6) & (m < 18)] = mult_markup
    # Distribution: 18~24 → mult_dist
    out[(m >= 18) & (m < 24)] = mult_dist
    # Markdown: 30~42 → mult_markdown (사이클 후반 베어)
    # (24~30은 1.0 유지 — accumulation 진입)
    out[(m >= 30) & (m < 42)] = mult_markdown
    # NaN(반감기 이전) → 1.0 유지
    return pd.Series(out, index=months.index, name="multiplier")


@dataclass
class CycleAwareEnsemble(Strategy):
    # ADX 게이트 (price regime)
    adx_period: int = 14
    adx_lo: float = 20.0
    adx_hi: float = 25.0
    # 추세 필터
    sma_period: int = 200
    # Vol targeting
    vol_window: int = 30
    target_vol: float = 0.40
    max_leverage: float = 1.0
    # Cycle multipliers (target_vol에 곱해져서 사이즈를 실제로 확대/축소)
    # apply_cycle=False면 BTC 반감기 가중치 비활성화 (ETH/SOL 등 비-BTC 자산에 권장)
    apply_cycle: bool = True
    mult_markup: float = 1.2
    mult_distribution: float = 0.7
    mult_markdown: float = 0.5
    # ATR percentile 위험 회피 (ADX와 분리된 자체 기간)
    atr_period: int = 14
    atr_pct_window: int = 252
    atr_risk_off_pct: float = 0.90
    atr_risk_off_scale: float = 0.5

    name: str = "cycle_aware"

    def generate_signals(self, ohlcv: pd.DataFrame) -> Signal:
        required = {"open", "high", "low", "close"}
        missing = required - set(ohlcv.columns)
        if missing:
            raise ValueError(f"OHLCV missing columns: {missing}")

        # 1. Sub-strategy 신호 (둘 다 디폴트 파라미터 사용)
        trend_sig = DonchianATR().generate_signals(ohlcv).reindex(ohlcv.index).fillna(0.0)
        mr_sig = ConnorsRSI().generate_signals(ohlcv).reindex(ohlcv.index).fillna(0.0)

        # 2. Price regime weight (ADX soft weighting)
        adx_series = adx(ohlcv, self.adx_period)
        w_trend = ((adx_series - self.adx_lo) /
                   (self.adx_hi - self.adx_lo)).clip(0, 1).fillna(0)

        # SMA200 필터: below SMA면 추세 가중치 0 (CRSI 단독)
        sma = ohlcv["close"].rolling(self.sma_period, min_periods=self.sma_period).mean()
        below_sma = ohlcv["close"] < sma
        w_trend = w_trend.where(~below_sma.fillna(False), 0.0)

        w_mr = 1.0 - w_trend

        # 3. 신호 결합 (가중 평균)
        combined = w_trend * trend_sig.clip(0, 1) + w_mr * mr_sig.clip(0, 1)

        # 4. Cycle multiplier (target_vol에 곱해 사이즈를 phase별로 스케일).
        #    apply_cycle=False면 1.0 고정 → 비-BTC 자산에서 의미 없는 가중치 회피.
        if self.apply_cycle:
            months = _months_since_last_halving(ohlcv.index)
            cycle_mult = _phase_multiplier(
                months, self.mult_markup, self.mult_distribution, self.mult_markdown,
            )
        else:
            cycle_mult = pd.Series(1.0, index=ohlcv.index, name="multiplier")

        # 5. Vol-targeting (cycle_mult를 target_vol에 적용 → markup 부스터가
        #    final clip에 먹히지 않고 사이즈에서 실제로 작동)
        rv = realized_vol(ohlcv["close"], self.vol_window)
        effective_target = self.target_vol * cycle_mult
        size = (effective_target / rv).where(rv > 0, 0.0).clip(0, self.max_leverage)

        # 6. ATR percentile 위험 회피 (adx_period와 분리)
        atr_series = atr(ohlcv, self.atr_period)
        atr_norm = atr_series / ohlcv["close"]
        atr_pct = atr_norm.rolling(
            self.atr_pct_window, min_periods=min(60, self.atr_pct_window)
        ).rank(pct=True)
        risk_off = (atr_pct > self.atr_risk_off_pct).fillna(False)

        # 7. 최종 포지션
        position = combined * size
        position = position.where(~risk_off, position * self.atr_risk_off_scale)
        position = position.clip(0.0, self.max_leverage).fillna(0.0)
        position.name = "signal"
        return position
