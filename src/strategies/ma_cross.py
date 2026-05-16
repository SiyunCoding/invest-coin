"""이동평균 크로스 전략 (Moving Average Crossover).

- 단기(fast) MA가 장기(slow) MA를 상향 돌파(golden cross)하면 매수.
- 단기 MA가 장기 MA를 하향 돌파(dead cross)하면 매도.

기본값: fast=20일, slow=60일.
신호는 i 시점까지의 종가만 사용 → 백테스트 엔진이 한 봉 미뤄 적용.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .base import Signal, Strategy


@dataclass
class MACross(Strategy):
    fast: int = 20
    slow: int = 60
    name: str = "ma_cross"

    def generate_signals(self, ohlcv: pd.DataFrame) -> Signal:
        if self.fast <= 0 or self.slow <= 0:
            raise ValueError("fast/slow must be positive")
        if self.fast >= self.slow:
            raise ValueError(f"fast({self.fast}) must be < slow({self.slow})")
        if "close" not in ohlcv.columns:
            raise ValueError("OHLCV missing 'close' column")

        close = ohlcv["close"]
        fast_ma = close.rolling(self.fast, min_periods=self.fast).mean()
        slow_ma = close.rolling(self.slow, min_periods=self.slow).mean()
        signal = (fast_ma > slow_ma).astype(float)
        signal[fast_ma.isna() | slow_ma.isna()] = 0.0
        signal.name = "signal"
        return signal