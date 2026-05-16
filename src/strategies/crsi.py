"""Connors RSI (CRSI) — Larry Connors의 단기 평균회귀 합성 지표.

CRSI = ( RSI(close, rsi_period)
       + RSI(UpDownLength, updown_period)
       + PercentRank(ROC(close, 1), pct_lookback) ) / 3

- UpDownLength: 종가가 연속 상승하면 +1씩, 연속 하락하면 -1씩 누적. 방향 바뀌면 ±1로 리셋.
- PercentRank: 최근 N봉 ROC 중 오늘 ROC의 백분위(0~100).

진입(롱):
  close > SMA(trend_period)  AND  CRSI < lower
청산:
  CRSI > upper  OR  close > SMA(exit_period)

코인은 변동성이 커 lower=5 정도가 적합 (전통 자산은 10).
SMA 추세 필터(기본 100)로 하락장 진입을 차단.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..utils.indicators import wilder_rsi
from .base import Signal, Strategy


def _up_down_length(close: pd.Series) -> pd.Series:
    diff = close.diff()
    direction = np.sign(diff.fillna(0.0)).astype(int).to_numpy()
    udl = np.zeros(len(direction), dtype=float)
    prev = 0
    for i in range(len(direction)):
        d = direction[i]
        if d == 0:
            prev = 0
        elif d > 0:
            prev = prev + 1 if prev > 0 else 1
        else:
            prev = prev - 1 if prev < 0 else -1
        udl[i] = prev
    return pd.Series(udl, index=close.index, name="udl")


def _percent_rank(series: pd.Series, lookback: int) -> pd.Series:
    """오늘 값이 최근 lookback봉 중 몇 퍼센타일인지 (0~100)."""
    def _rank(window):
        if len(window) < 2:
            return np.nan
        last = window[-1]
        return float((window[:-1] < last).sum()) / (len(window) - 1) * 100.0

    return series.rolling(lookback, min_periods=lookback).apply(_rank, raw=True)


@dataclass
class ConnorsRSI(Strategy):
    rsi_period: int = 3
    updown_period: int = 2
    pct_lookback: int = 100
    # 코인 walk-forward 검증으로 결정. Connors 원안(lower=10, trend=200)은 전통자산용이라
    # 코인에는 신호가 거의 안 뜸. 20/150이 IS->OOS decay가 가장 작음.
    lower: float = 20.0
    upper: float = 70.0
    trend_period: int = 150
    exit_period: int = 5
    name: str = "crsi"

    def generate_signals(self, ohlcv: pd.DataFrame) -> Signal:
        if self.rsi_period < 2 or self.updown_period < 2:
            raise ValueError("rsi_period and updown_period must be >= 2")
        if not 0 < self.lower < self.upper < 100:
            raise ValueError("require 0 < lower < upper < 100")
        if "close" not in ohlcv.columns:
            raise ValueError("OHLCV missing 'close' column")

        close = ohlcv["close"]
        rsi_close = wilder_rsi(close, self.rsi_period)
        udl = _up_down_length(close)
        rsi_udl = wilder_rsi(udl, self.updown_period)
        roc = close.pct_change()
        pct_rank = _percent_rank(roc, self.pct_lookback)
        crsi = (rsi_close + rsi_udl + pct_rank) / 3.0

        trend_ma = close.rolling(self.trend_period, min_periods=self.trend_period).mean()
        exit_ma = close.rolling(self.exit_period, min_periods=self.exit_period).mean()

        in_uptrend = close > trend_ma
        buy = (crsi < self.lower) & in_uptrend
        sell = (crsi > self.upper) | (close > exit_ma)

        position = np.zeros(len(ohlcv), dtype=float)
        buy_arr = buy.fillna(False).to_numpy()
        sell_arr = sell.fillna(False).to_numpy()
        crsi_arr = crsi.to_numpy()
        held = 0.0
        for i in range(len(ohlcv)):
            if np.isnan(crsi_arr[i]):
                position[i] = 0.0
                continue
            if held == 0.0 and buy_arr[i]:
                held = 1.0
            elif held == 1.0 and sell_arr[i]:
                held = 0.0
            position[i] = held

        return pd.Series(position, index=ohlcv.index, name="signal")