"""여러 코인을 같은 전략/파라미터로 동시 백테스트해 비교."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..data import load_ohlcv
from ..strategies import REGISTRY
from .engine import BacktestResult, run_backtest


@dataclass
class MultiCoinResult:
    summary: pd.DataFrame             # 코인별 지표 한 줄씩
    equity_curves: pd.DataFrame       # index=시각, columns=코인
    results: dict[str, BacktestResult]


def run_multi_coin(
    symbols: list[str],
    strategy_name: str,
    strategy_params: dict,
    interval: str = "1d",
    lookback_days: int = 365,
    cache_dir: str = "data",
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.001,
    slippage_rate: float = 0.0005,
    refresh: bool = False,
) -> MultiCoinResult:
    if strategy_name not in REGISTRY:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    cls = REGISTRY[strategy_name].cls

    rows = []
    results: dict[str, BacktestResult] = {}
    curves: dict[str, pd.Series] = {}

    for symbol in symbols:
        try:
            ohlcv = load_ohlcv(
                symbol=symbol, interval=interval,
                lookback_days=lookback_days, cache_dir=cache_dir, refresh=refresh,
            )
            if ohlcv.empty:
                rows.append({"symbol": symbol, "error": "no data"})
                continue
            strategy = cls(**strategy_params)
            result = run_backtest(
                ohlcv=ohlcv, strategy=strategy,
                initial_capital=initial_capital,
                fee_rate=fee_rate, slippage_rate=slippage_rate,
            )
            results[symbol] = result
            curves[symbol] = result.equity
            bh = float(ohlcv["close"].iloc[-1] / ohlcv["close"].iloc[0] - 1)
            rows.append({
                "symbol": symbol,
                **result.metrics,
                "buy_and_hold": bh,
                "vs_bh": result.metrics["total_return"] - bh,
            })
        except Exception as e:
            rows.append({"symbol": symbol, "error": str(e)})

    summary = pd.DataFrame(rows)
    if curves:
        equity_curves = pd.concat(curves, axis=1).ffill()
    else:
        equity_curves = pd.DataFrame()
    return MultiCoinResult(summary=summary, equity_curves=equity_curves, results=results)