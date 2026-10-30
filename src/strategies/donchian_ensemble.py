"""Donchian 앙상블 추세추종 전략 (백테스트/Streamlit 용 래퍼).

신호 계산은 src/portfolio/signals.py (라이브와 공용). 비중 = frac × min(target_vol/σ90, max_weight).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..portfolio.signals import DEFAULT_LOOKBACKS, trend_fraction, vol_scale
from .base import Signal, Strategy


@dataclass
class DonchianEnsemble(Strategy):
    target_vol: float = 0.40
    vol_window: int = 90
    max_weight: float = 1.0
    lookbacks: tuple[int, ...] = DEFAULT_LOOKBACKS
    name: str = "donchian_ensemble"

    def generate_signals(self, ohlcv: pd.DataFrame) -> Signal:
        if "close" not in ohlcv.columns:
            raise ValueError("OHLCV missing 'close' column")
        if not 0 < self.target_vol <= 5:
            raise ValueError("target_vol must be in (0, 5]")
        close = ohlcv["close"]
        frac = trend_fraction(close, tuple(int(n) for n in self.lookbacks))
        size = vol_scale(close, self.target_vol, self.vol_window, self.max_weight)
        signal = (frac.reindex(ohlcv.index).fillna(0.0) * size).clip(0.0, self.max_weight)
        signal.name = "signal"
        return signal
