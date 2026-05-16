"""Larry Williams 변동성 돌파 + ATR Chandelier 추적 손절 + Vol Targeting.

기존 변동성 돌파의 약점:
- K=0.5는 신호 과다 → 수수료 학살
- 다음날 시가 청산이라 추세를 끝까지 못 탐
- 포지션 크기가 항상 1.0이라 변동성 폭증기 무방비

개선:
- 진입 시점은 동일 (당일 high >= open + K*(prev_h - prev_l))
- 진입 시 포지션 크기 = clip(target_vol / realized_vol, 0, max_lev)  # vol-target sizing
- 청산 = ATR Chandelier (highest_high_since_entry - atr_mult * ATR)  # 큰 추세 끝까지

코인 일봉 권장: K=0.5, atr_mult=3.0, target_vol=0.40
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..utils.indicators import PERIODS_PER_YEAR_DAILY, atr, realized_vol
from .base import Signal, Strategy


@dataclass
class LarryATR(Strategy):
    k: float = 0.5
    atr_period: int = 14
    atr_mult: float = 3.0
    vol_window: int = 30
    target_vol: float = 0.40
    max_leverage: float = 1.0
    annualize: int = PERIODS_PER_YEAR_DAILY
    name: str = "larry_atr"

    def generate_signals(self, ohlcv: pd.DataFrame) -> Signal:
        if not 0 < self.k <= 2:
            raise ValueError(f"k must be in (0, 2], got {self.k}")
        if self.atr_period < 2:
            raise ValueError("atr_period must be >= 2")
        if self.atr_mult <= 0:
            raise ValueError("atr_mult must be > 0")
        if not 0 < self.target_vol <= 5:
            raise ValueError("target_vol must be in (0, 5]")
        if not 0 < self.max_leverage <= 3:
            raise ValueError("max_leverage must be in (0, 3]")
        required = {"open", "high", "low", "close"}
        missing = required - set(ohlcv.columns)
        if missing:
            raise ValueError(f"OHLCV missing columns: {missing}")

        prev_range = (ohlcv["high"] - ohlcv["low"]).shift(1)
        target_price = ohlcv["open"] + prev_range * self.k
        breakout = ohlcv["high"] >= target_price

        atr_series = atr(ohlcv, self.atr_period)
        rv = realized_vol(ohlcv["close"], window=self.vol_window, annualize=self.annualize)
        size_target = (self.target_vol / rv).where(rv > 0, 0.0)
        size_target = size_target.clip(lower=0.0, upper=self.max_leverage)

        breakout_arr = breakout.fillna(False).to_numpy()
        high_arr = ohlcv["high"].to_numpy()
        close_arr = ohlcv["close"].to_numpy()
        target_arr = target_price.to_numpy()
        atr_arr = atr_series.to_numpy()
        size_arr = size_target.to_numpy()

        position = np.zeros(len(ohlcv), dtype=float)
        held_size = 0.0
        highest_since_entry = -np.inf
        trail_stop = -np.inf

        for i in range(len(ohlcv)):
            if (np.isnan(target_arr[i]) or np.isnan(atr_arr[i])
                    or np.isnan(size_arr[i])):
                position[i] = 0.0
                continue
            if held_size == 0.0:
                if breakout_arr[i] and size_arr[i] > 0:
                    held_size = float(size_arr[i])
                    highest_since_entry = high_arr[i]
                    trail_stop = highest_since_entry - self.atr_mult * atr_arr[i]
            else:
                highest_since_entry = max(highest_since_entry, high_arr[i])
                new_stop = highest_since_entry - self.atr_mult * atr_arr[i]
                trail_stop = max(trail_stop, new_stop)
                if close_arr[i] < trail_stop:
                    held_size = 0.0
                    highest_since_entry = -np.inf
                    trail_stop = -np.inf
            position[i] = held_size

        return pd.Series(position, index=ohlcv.index, name="signal")
