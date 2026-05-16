"""파라미터 그리드 서치 최적화.

전략 파라미터 조합을 모두 백테스트하고 지표 기준으로 정렬한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Iterable, Mapping

import pandas as pd

from ..strategies import REGISTRY, ParamSpec
from .engine import run_backtest


@dataclass
class OptimizationResult:
    table: pd.DataFrame  # 파라미터 + 지표
    best_params: dict
    metric: str


def _expand_grid(grid: Mapping[str, Iterable]) -> list[dict]:
    keys = list(grid.keys())
    combos = []
    for values in product(*(grid[k] for k in keys)):
        combos.append(dict(zip(keys, values)))
    return combos


def _coerce(spec: ParamSpec, v):
    if spec.kind == "bool":
        return bool(v)
    if spec.kind == "int":
        return int(round(v))
    return float(v)


def grid_search(
    ohlcv: pd.DataFrame,
    strategy_name: str,
    grid: Mapping[str, Iterable],
    metric: str = "sharpe",
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.001,
    slippage_rate: float = 0.0005,
) -> OptimizationResult:
    """grid는 {param_name: [val, ...]}. 모든 조합을 백테스트.

    metric: "sharpe" | "total_return" | "cagr" | "max_drawdown" (MDD는 작을수록 좋음).
    """
    if strategy_name not in REGISTRY:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    meta = REGISTRY[strategy_name]
    spec_by_name = {s.name: s for s in meta.params}

    rows = []
    for combo in _expand_grid(grid):
        params = {k: _coerce(spec_by_name[k], v) for k, v in combo.items()}
        try:
            strategy = meta.cls(**params)
            result = run_backtest(
                ohlcv=ohlcv, strategy=strategy,
                initial_capital=initial_capital,
                fee_rate=fee_rate, slippage_rate=slippage_rate,
            )
            row = {**params, **result.metrics}
        except Exception as e:
            row = {**params, "error": str(e)}
        rows.append(row)

    df = pd.DataFrame(rows)
    if metric not in df.columns:
        raise ValueError(f"metric '{metric}' not in results")

    ascending = metric == "max_drawdown"  # MDD는 0에 가까울수록 좋음 → 내림차순(덜 음수)
    sorted_df = df.sort_values(metric, ascending=ascending, na_position="last").reset_index(drop=True)
    best_row = sorted_df.iloc[0].to_dict()
    best_params = {k: best_row[k] for k in grid.keys()}
    return OptimizationResult(table=sorted_df, best_params=best_params, metric=metric)