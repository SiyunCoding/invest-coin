"""공용 기술 지표.

전 전략에서 재사용되는 함수만 모아둔다 (ATR, Wilder RSI, 변동성 등).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# 코인은 24/7 → 연환산 365일
PERIODS_PER_YEAR_DAILY = 365


def wilder_rsi(series: pd.Series, period: int) -> pd.Series:
    """Wilder smoothing RSI. period < 2면 에러."""
    if period < 2:
        raise ValueError("period must be >= 2")
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(ohlcv: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder smoothing).

    TR_t = max(H-L, |H-PrevClose|, |L-PrevClose|)
    ATR_t = Wilder EWM of TR
    """
    if period < 2:
        raise ValueError("period must be >= 2")
    high = ohlcv["high"]
    low = ohlcv["low"]
    prev_close = ohlcv["close"].shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def adx(ohlcv: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index (Wilder).

    추세 강도를 0~100으로 측정. 25 이상이면 강한 추세, 20 이하면 무추세.
    """
    if period < 2:
        raise ValueError("period must be >= 2")
    high = ohlcv["high"]
    low = ohlcv["low"]
    close = ohlcv["close"]

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=close.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=close.index,
    )
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)

    atr_series = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    pdi = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_series
    mdi = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_series
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def realized_vol(
    close: pd.Series,
    window: int = 30,
    annualize: int = PERIODS_PER_YEAR_DAILY,
) -> pd.Series:
    """봉 단위 로그수익률의 EWMA 표준편차 × √annualize.

    EWMA는 halflife=window/2로 가중. 일봉/4시간봉 모두 사용 가능
    (annualize 인자만 봉당 연 환산 계수에 맞게 넘겨주면 됨).
    """
    if window < 2:
        raise ValueError("window must be >= 2")
    log_ret = np.log(close / close.shift(1))
    vol = log_ret.ewm(halflife=window / 2, min_periods=window, adjust=False).std()
    return vol * np.sqrt(annualize)
