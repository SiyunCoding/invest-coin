"""변동성 돌파 전략 (Larry Williams).

매수 조건: 당일 고가가 target 라인을 상향 돌파
  target_i = open_i + (high_{i-1} - low_{i-1}) * K

신호 시점 i에서 high_i >= target_i 이면 1, 아니면 0.
백테스트 엔진이 한 칸 미뤄 적용하므로 lookahead bias 없음.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .base import Signal, Strategy


@dataclass
class VolatilityBreakout(Strategy):
    k: float = 0.5
    name: str = "volatility_breakout"

    def generate_signals(self, ohlcv: pd.DataFrame) -> Signal:
        if not 0 < self.k <= 2:
            raise ValueError(f"k must be in (0, 2], got {self.k}")
        required = {"open", "high", "low", "close"}
        missing = required - set(ohlcv.columns)
        if missing:
            raise ValueError(f"OHLCV missing columns: {missing}")

        prev_range = (ohlcv["high"] - ohlcv["low"]).shift(1)
        target = ohlcv["open"] + prev_range * self.k
        signal = (ohlcv["high"] >= target).astype(float)
        signal.iloc[0] = 0.0
        signal.name = "signal"
        return signal
