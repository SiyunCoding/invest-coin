"""성과 지표 계산: 누적수익률, CAGR, MDD, 샤프, 승률, 거래 수."""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 365  # 코인은 24/7


def _periods_per_year(index: pd.DatetimeIndex) -> float:
    if len(index) < 2:
        return TRADING_DAYS_PER_YEAR
    deltas = index.to_series().diff().dropna()
    if deltas.empty:
        return TRADING_DAYS_PER_YEAR
    median_seconds = deltas.median().total_seconds()
    if median_seconds <= 0:
        return TRADING_DAYS_PER_YEAR
    return (365 * 24 * 3600) / median_seconds


def total_return(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    return float(equity.iloc[-1] / equity.iloc[0] - 1)


def cagr(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    start, end = equity.index[0], equity.index[-1]
    years = max((end - start).total_seconds() / (365 * 24 * 3600), 1e-9)
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1)


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    drawdown = equity / running_max - 1
    return float(drawdown.min())


def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0) -> float:
    if returns.empty or returns.std() == 0:
        return 0.0
    ppy = _periods_per_year(returns.index)
    excess = returns - risk_free_rate / ppy
    return float(excess.mean() / excess.std() * np.sqrt(ppy))


def win_rate(trade_returns: pd.Series) -> float:
    if trade_returns.empty:
        return 0.0
    wins = (trade_returns > 0).sum()
    return float(wins / len(trade_returns))


def compute_metrics(
    equity: pd.Series,
    returns: pd.Series,
    trade_returns: pd.Series,
) -> dict:
    return {
        "total_return": total_return(equity),
        "cagr": cagr(equity),
        "max_drawdown": max_drawdown(equity),
        "sharpe": sharpe_ratio(returns),
        "win_rate": win_rate(trade_returns),
        "num_trades": int(len(trade_returns)),
    }
