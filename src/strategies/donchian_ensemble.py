"""Donchian 앙상블 추세추종 (Zarattini, Pagani, Barbon 2025 "Catching Crypto Trends" Combo).

규칙 (기간 n 마다 독립):
  DonchianUp/Down = 최근 n개 종가의 max/min (당일 포함), Mid = (Up+Down)/2
  진입: 종가 >= DonchianUp (n일 최고 종가)
  손절선: 진입 시 Mid, 이후 매일 max(이전 손절선, 오늘 Mid)  (내려가지 않음)
  청산: 종가 < 손절선
frac = 보유 중인 기간 수 / 전체 기간 수  (0~1)
비중 = frac × min(target_vol / σ90, max_weight)   σ90 = 90일 연환산 변동성

lookahead 없음: i 시점 신호는 i 시점 종가까지만 사용. 엔진/실매매가 다음 봉에 반영.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .base import Signal, Strategy

DEFAULT_LOOKBACKS: tuple[int, ...] = (5, 10, 20, 30, 60, 90, 150, 250, 360)


def donchian_position(close: pd.Series, n: int) -> pd.Series:
    """n일 Donchian 진입 + 중앙선 래칫 손절의 보유 상태(0/1)."""
    up = close.rolling(n, min_periods=n).max().to_numpy()
    dn = close.rolling(n, min_periods=n).min().to_numpy()
    mid = (up + dn) / 2
    c = close.to_numpy()
    pos = np.zeros(len(c))
    held, stop = 0.0, -np.inf
    for i in range(len(c)):
        if np.isnan(up[i]):
            continue
        if held == 0.0:
            if c[i] >= up[i]:
                held, stop = 1.0, mid[i]
        else:
            if c[i] < stop:
                held, stop = 0.0, -np.inf
            else:
                stop = max(stop, mid[i])
        pos[i] = held
    return pd.Series(pos, index=close.index)


def trend_fraction(close: pd.Series, lookbacks: tuple[int, ...] = DEFAULT_LOOKBACKS) -> pd.Series:
    """보유 중인 Donchian 기간의 비율 (0~1)."""
    close = close.dropna()
    return sum(donchian_position(close, n) for n in lookbacks) / len(lookbacks)


def annualized_vol(close: pd.Series, window: int = 90) -> pd.Series:
    """일간 수익률 표준편차 × √365 (코인 24/7)."""
    return close.pct_change().rolling(window, min_periods=window).std() * np.sqrt(365)


def vol_scale(close: pd.Series, target_vol: float, window: int = 90, cap: float = 1.0) -> pd.Series:
    """min(target_vol / σ, cap). 변동성 데이터 부족 구간은 0."""
    sigma = annualized_vol(close, window)
    return (target_vol / sigma).where(sigma > 0).clip(upper=cap).fillna(0.0)


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
