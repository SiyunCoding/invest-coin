"""Donchian Breakout + ATR Chandelier Trailing Stop — Turtle 현대화 버전.

진입: close > max(high[t-N..t-1])     # N일 신고가 종가 돌파
청산: close < trailing_stop
  trailing_stop = max(highest_high_since_entry - atr_mult * ATR(atr_period), prev_stop)

ATR (Wilder): TR = max(H-L, |H-PrevClose|, |L-PrevClose|), ATR = Wilder smooth.

코인 일봉에서 lookback=20, atr_period=14, atr_mult=3.0 권장.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..utils.indicators import atr
from .base import Signal, Strategy


@dataclass
class DonchianATR(Strategy):
    lookback: int = 20
    atr_period: int = 14
    atr_mult: float = 3.0
    name: str = "donchian_atr"

    def generate_signals(self, ohlcv: pd.DataFrame) -> Signal:
        if self.lookback < 2:
            raise ValueError("lookback must be >= 2")
        if self.atr_period < 2:
            raise ValueError("atr_period must be >= 2")
        if self.atr_mult <= 0:
            raise ValueError("atr_mult must be > 0")
        missing = {"open", "high", "low", "close"} - set(ohlcv.columns)
        if missing:
            raise ValueError(f"OHLCV missing columns: {missing}")

        close = ohlcv["close"]
        donchian_high = ohlcv["high"].shift(1).rolling(
            self.lookback, min_periods=self.lookback
        ).max()
        atr_series = atr(ohlcv, self.atr_period)

        close_arr = close.to_numpy()
        high_arr = ohlcv["high"].to_numpy()
        donchian_arr = donchian_high.to_numpy()
        atr_arr = atr_series.to_numpy()

        position = np.zeros(len(ohlcv), dtype=float)
        held = 0.0
        highest_since_entry = -np.inf
        trail_stop = -np.inf

        for i in range(len(ohlcv)):
            if np.isnan(donchian_arr[i]) or np.isnan(atr_arr[i]):
                position[i] = 0.0
                continue
            if held == 0.0:
                if close_arr[i] > donchian_arr[i]:
                    held = 1.0
                    highest_since_entry = high_arr[i]
                    trail_stop = highest_since_entry - self.atr_mult * atr_arr[i]
            else:
                highest_since_entry = max(highest_since_entry, high_arr[i])
                new_stop = highest_since_entry - self.atr_mult * atr_arr[i]
                trail_stop = max(trail_stop, new_stop)
                if close_arr[i] < trail_stop:
                    held = 0.0
                    highest_since_entry = -np.inf
                    trail_stop = -np.inf
            position[i] = held

        return pd.Series(position, index=ohlcv.index, name="signal")