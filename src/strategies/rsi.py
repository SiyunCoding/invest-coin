"""RSI 기반 평균회귀 전략.

- RSI가 oversold(예: 30) 아래로 내려갔다가 다시 그 위로 올라오면 매수.
- RSI가 overbought(예: 70) 위로 올라갔다가 다시 그 아래로 내려오면 매도.

상태 머신 방식: 한 번 진입하면 매도 신호가 나오기 전까지 보유 유지.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..utils.indicators import wilder_rsi
from .base import Signal, Strategy


@dataclass
class RSIStrategy(Strategy):
    period: int = 14
    oversold: float = 30.0
    overbought: float = 70.0
    name: str = "rsi"

    def generate_signals(self, ohlcv: pd.DataFrame) -> Signal:
        if self.period < 2:
            raise ValueError("period must be >= 2")
        if not 0 < self.oversold < self.overbought < 100:
            raise ValueError("require 0 < oversold < overbought < 100")
        if "close" not in ohlcv.columns:
            raise ValueError("OHLCV missing 'close' column")

        rsi = wilder_rsi(ohlcv["close"], self.period)

        # cross-up from oversold → buy, cross-down from overbought → sell
        prev_rsi = rsi.shift(1)
        buy = (prev_rsi <= self.oversold) & (rsi > self.oversold)
        sell = (prev_rsi >= self.overbought) & (rsi < self.overbought)

        position = np.zeros(len(ohlcv), dtype=float)
        held = 0.0
        buy_arr = buy.to_numpy()
        sell_arr = sell.to_numpy()
        rsi_arr = rsi.to_numpy()
        for i in range(len(ohlcv)):
            if np.isnan(rsi_arr[i]):
                position[i] = 0.0
                continue
            if held == 0.0 and buy_arr[i]:
                held = 1.0
            elif held == 1.0 and sell_arr[i]:
                held = 0.0
            position[i] = held

        signal = pd.Series(position, index=ohlcv.index, name="signal")
        return signal