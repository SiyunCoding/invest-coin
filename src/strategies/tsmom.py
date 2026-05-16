"""Volatility-Targeted Time-Series Momentum (TSMOM).

Moskowitz, Ooi, Pedersen (2012) 원안의 코인 변형.

신호 (롱 온리):
  momentum_t = close_t / close_{t-K} - 1
  if momentum_t > 0:
      position_t = clip( target_vol / realized_vol_t, 0, max_leverage )
  else:
      position_t = 0

핵심:
- 모멘텀 부호로 진입 결정
- 포지션 크기를 realized_vol에 반비례시켜 변동성 폭증기 자동 deleverage
- 이게 TSMOM 알파의 대부분이라고 학계가 검증 (Moskowitz 2012)

코인은 24/7이라 연환산 계수 365 (일봉 기준).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..utils.indicators import PERIODS_PER_YEAR_DAILY, realized_vol
from .base import Signal, Strategy


@dataclass
class VolTargetedTSMOM(Strategy):
    lookback: int = 60
    vol_window: int = 30
    target_vol: float = 0.40
    max_leverage: float = 1.0
    annualize: int = PERIODS_PER_YEAR_DAILY
    name: str = "tsmom"

    def generate_signals(self, ohlcv: pd.DataFrame) -> Signal:
        if self.lookback < 2:
            raise ValueError("lookback must be >= 2")
        if self.vol_window < 2:
            raise ValueError("vol_window must be >= 2")
        if not 0 < self.target_vol <= 5:
            raise ValueError("target_vol must be in (0, 5]")
        if not 0 < self.max_leverage <= 3:
            raise ValueError("max_leverage must be in (0, 3]")
        if "close" not in ohlcv.columns:
            raise ValueError("OHLCV missing 'close' column")

        close = ohlcv["close"]
        momentum = close / close.shift(self.lookback) - 1.0
        rv = realized_vol(close, window=self.vol_window, annualize=self.annualize)

        # 변동성이 너무 작은 봉(NaN/0)은 사이즈 0
        scale = (self.target_vol / rv).where(rv > 0, 0.0)
        scale = scale.clip(lower=0.0, upper=self.max_leverage)

        long_mask = (momentum > 0) & momentum.notna() & scale.notna()
        position = np.where(long_mask, scale.fillna(0.0).to_numpy(), 0.0)
        return pd.Series(position, index=ohlcv.index, name="signal")
