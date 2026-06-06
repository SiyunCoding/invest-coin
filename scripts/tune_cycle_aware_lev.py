"""cycle_aware max_leverage walk-forward 그리드 서치."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest import run_backtest
from src.data import load_ohlcv
from src.strategies import REGISTRY


def evaluate(ohlcv: pd.DataFrame, params: dict) -> dict:
    strategy = REGISTRY["cycle_aware"].cls(**params)
    r = run_backtest(
        ohlcv=ohlcv, strategy=strategy,
        initial_capital=10_000, fee_rate=0.001, slippage_rate=0.0005,
    )
    return {
        "ret": r.metrics["total_return"],
        "sharpe": r.metrics["sharpe"],
        "mdd": r.metrics["max_drawdown"],
        "trades": r.metrics["num_trades"],
    }


def main() -> int:
    print("=" * 88)
    print("cycle_aware max_leverage walk-forward 그리드 서치")
    print("=" * 88)

    ohlcv = load_ohlcv(symbol="BTCUSDT", interval="1d", lookback_days=1825,
                      cache_dir=ROOT / "data")
    print(f"\n데이터: {len(ohlcv)} bars, {ohlcv.index.min().date()} ~ {ohlcv.index.max().date()}")

    n = len(ohlcv)
    is_ohlcv = ohlcv.iloc[:n // 2]
    oos_ohlcv = ohlcv.iloc[n // 2:]

    print(f"\nIS  ({len(is_ohlcv)} bars): {is_ohlcv.index.min().date()} ~ {is_ohlcv.index.max().date()}")
    print(f"OOS ({len(oos_ohlcv)} bars): {oos_ohlcv.index.min().date()} ~ {oos_ohlcv.index.max().date()}")

    grid = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]

    print("\n" + "=" * 88)
    print("IS 그리드 서치 (max_leverage 변화)")
    print("=" * 88)
    print(f"{'max_lev':>10s}  {'ret':>10s}  {'Sharpe':>8s}  {'MDD':>10s}  {'trades':>7s}")

    is_results = []
    for lev in grid:
        r = evaluate(is_ohlcv, {"max_leverage": lev})
        is_results.append((lev, r))
        print(f"{lev:>10.2f}  {r['ret']*100:>+9.2f}%  {r['sharpe']:>8.3f}  {r['mdd']*100:>+9.2f}%  {r['trades']:>7d}")

    best = max(is_results, key=lambda x: x[1]["sharpe"])
    best_lev, best_is = best
    print(f"\n→ IS 최고 Sharpe: max_leverage = {best_lev} (Sharpe {best_is['sharpe']:.3f})")

    print("\n" + "=" * 88)
    print("OOS 검증")
    print("=" * 88)
    print(f"{'전략':<25s}  {'ret':>10s}  {'Sharpe':>8s}  {'MDD':>10s}  {'trades':>7s}")

    for lev in grid:
        r = evaluate(oos_ohlcv, {"max_leverage": lev})
        marker = " ← IS best" if lev == best_lev else ""
        marker = " ← baseline" if lev == 1.0 else marker
        print(f"{f'max_lev={lev}':<25s}  {r['ret']*100:>+9.2f}%  {r['sharpe']:>8.3f}  "
              f"{r['mdd']*100:>+9.2f}%  {r['trades']:>7d}{marker}")

    print("\n" + "=" * 88)
    print("전체 5년 비교")
    print("=" * 88)
    print(f"{'전략':<25s}  {'ret':>10s}  {'Sharpe':>8s}  {'MDD':>10s}")
    for lev in grid:
        r = evaluate(ohlcv, {"max_leverage": lev})
        print(f"{f'max_lev={lev}':<25s}  {r['ret']*100:>+9.2f}%  {r['sharpe']:>8.3f}  {r['mdd']*100:>+9.2f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
