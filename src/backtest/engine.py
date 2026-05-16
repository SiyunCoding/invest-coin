"""백테스트 엔진.

원칙:
- 전략의 신호 s[i]는 i 시점까지의 정보로 만들어짐 (lookahead 금지).
- 실제 포지션은 한 봉 뒤로 미뤄 적용: position[i] = s[i-1].
- 봉 수익률 = position[i] * (close[i]/close[i-1] - 1).
- 포지션이 바뀌는 봉에서 수수료 + 슬리피지 차감.
- 매매 단위: 풀포지션 (현금 ↔ 코인). 부분 포지션은 추후 확장.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..strategies.base import Strategy
from .metrics import compute_metrics


@dataclass
class BacktestResult:
    equity: pd.Series
    returns: pd.Series
    position: pd.Series
    trades: pd.DataFrame
    metrics: dict
    ohlcv: pd.DataFrame = field(repr=False)
    signal: pd.Series = field(repr=False)


def _extract_trades(
    ohlcv: pd.DataFrame, position: pd.Series, equity: pd.Series
) -> pd.DataFrame:
    """포지션 변화점에서 진입/청산 가격을 추출해 거래 단위로 묶는다."""
    pos = position.fillna(0.0).to_numpy()
    closes = ohlcv["close"].to_numpy()
    times = ohlcv.index
    equity_arr = equity.to_numpy()

    trades = []
    in_pos = False
    entry_i = -1
    for i in range(len(pos)):
        if not in_pos and pos[i] > 0:
            in_pos = True
            entry_i = i
        elif in_pos and pos[i] == 0:
            exit_i = i
            ret = closes[exit_i] / closes[entry_i] - 1
            equity_ret = equity_arr[exit_i] / equity_arr[entry_i] - 1
            trades.append({
                "entry_time": times[entry_i],
                "exit_time": times[exit_i],
                "entry_price": float(closes[entry_i]),
                "exit_price": float(closes[exit_i]),
                "gross_return": float(ret),
                "net_return": float(equity_ret),
            })
            in_pos = False
    if in_pos:
        exit_i = len(pos) - 1
        ret = closes[exit_i] / closes[entry_i] - 1
        equity_ret = equity_arr[exit_i] / equity_arr[entry_i] - 1
        trades.append({
            "entry_time": times[entry_i],
            "exit_time": times[exit_i],
            "entry_price": float(closes[entry_i]),
            "exit_price": float(closes[exit_i]),
            "gross_return": float(ret),
            "net_return": float(equity_ret),
            "open": True,
        })
    return pd.DataFrame(trades)


def run_backtest(
    ohlcv: pd.DataFrame,
    strategy: Strategy,
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.001,
    slippage_rate: float = 0.0005,
) -> BacktestResult:
    if ohlcv.empty:
        raise ValueError("OHLCV is empty")

    signal = strategy.generate_signals(ohlcv).reindex(ohlcv.index).fillna(0.0)

    # lookahead 방지: 한 봉 뒤로 미뤄 실제 포지션 결정
    position = signal.shift(1).fillna(0.0)

    close = ohlcv["close"]
    bar_returns = close.pct_change().fillna(0.0)
    gross_returns = position * bar_returns

    # 포지션 변화 시 거래비용 차감 (왕복 한쪽씩 적용)
    pos_change = position.diff().abs().fillna(position.abs())
    cost_rate = fee_rate + slippage_rate
    costs = pos_change * cost_rate

    net_returns = gross_returns - costs
    equity = (1 + net_returns).cumprod() * initial_capital

    trades = _extract_trades(ohlcv, position, equity)
    trade_returns = trades["net_return"] if not trades.empty else pd.Series(dtype=float)
    metrics = compute_metrics(equity, net_returns, trade_returns)

    return BacktestResult(
        equity=equity,
        returns=net_returns,
        position=position,
        trades=trades,
        metrics=metrics,
        ohlcv=ohlcv,
        signal=signal,
    )
