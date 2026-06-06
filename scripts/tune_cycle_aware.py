"""cycle_aware mult_markup walk-forward 그리드 서치.

IS (50% 데이터): mult_markup 그리드 평가 → 최고 Sharpe 값 선택
OOS (나머지 50%): 그 값을 OOS에 적용 → 진짜 개선인지 검증

판정:
  - OOS Sharpe ≥ baseline OOS Sharpe → 개선 채택
  - OOS Sharpe < baseline OOS Sharpe → over-fit, 채택 안 함
"""
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
    print("cycle_aware mult_markup walk-forward 그리드 서치")
    print("=" * 88)

    ohlcv = load_ohlcv(symbol="BTCUSDT", interval="1d", lookback_days=1825,
                      cache_dir=ROOT / "data")
    print(f"\n데이터: {len(ohlcv)} bars, {ohlcv.index.min().date()} ~ {ohlcv.index.max().date()}")

    n = len(ohlcv)
    is_ohlcv = ohlcv.iloc[:n // 2]
    oos_ohlcv = ohlcv.iloc[n // 2:]

    print(f"\nIS  ({len(is_ohlcv)} bars): {is_ohlcv.index.min().date()} ~ {is_ohlcv.index.max().date()}")
    print(f"OOS ({len(oos_ohlcv)} bars): {oos_ohlcv.index.min().date()} ~ {oos_ohlcv.index.max().date()}")

    grid = [1.0, 1.2, 1.5, 1.8, 2.1, 2.5, 3.0]

    print("\n" + "=" * 88)
    print("IS 그리드 서치 (mult_markup 변화, 다른 파라미터 디폴트)")
    print("=" * 88)
    print(f"{'mult_markup':>12s}  {'ret':>10s}  {'Sharpe':>8s}  {'MDD':>10s}  {'trades':>7s}")

    is_results = []
    for m in grid:
        params = {"mult_markup": m}
        r = evaluate(is_ohlcv, params)
        is_results.append((m, r))
        print(f"{m:>12.2f}  {r['ret']*100:>+9.2f}%  {r['sharpe']:>8.3f}  {r['mdd']*100:>+9.2f}%  {r['trades']:>7d}")

    # IS 최고 Sharpe 선택
    best = max(is_results, key=lambda x: x[1]["sharpe"])
    best_mult, best_is = best
    print(f"\n→ IS 최고 Sharpe: mult_markup = {best_mult} (Sharpe {best_is['sharpe']:.3f})")

    print("\n" + "=" * 88)
    print("OOS 검증 (IS 최고값 + 베이스라인 비교)")
    print("=" * 88)

    baseline_oos = evaluate(oos_ohlcv, {"mult_markup": 1.2})  # 기존 디폴트
    tuned_oos = evaluate(oos_ohlcv, {"mult_markup": best_mult})

    print(f"{'전략':<25s}  {'ret':>10s}  {'Sharpe':>8s}  {'MDD':>10s}  {'trades':>7s}")
    print(f"{'baseline (mult=1.2)':<25s}  {baseline_oos['ret']*100:>+9.2f}%  "
          f"{baseline_oos['sharpe']:>8.3f}  {baseline_oos['mdd']*100:>+9.2f}%  "
          f"{baseline_oos['trades']:>7d}")
    print(f"{f'tuned (mult={best_mult})':<25s}  {tuned_oos['ret']*100:>+9.2f}%  "
          f"{tuned_oos['sharpe']:>8.3f}  {tuned_oos['mdd']*100:>+9.2f}%  "
          f"{tuned_oos['trades']:>7d}")

    delta_sharpe = tuned_oos["sharpe"] - baseline_oos["sharpe"]
    delta_ret = (tuned_oos["ret"] - baseline_oos["ret"]) * 100

    print("\n" + "=" * 88)
    if delta_sharpe > 0.05 and delta_ret > 0:
        print(f"✅ 개선 채택 — OOS Sharpe +{delta_sharpe:.3f}, ret +{delta_ret:.2f}%p")
        print(f"   권장 디폴트: mult_markup = {best_mult}")
    elif abs(delta_sharpe) < 0.05:
        print(f"➖ 차이 미미 — OOS Sharpe Δ={delta_sharpe:+.3f}. 디폴트 유지 권장.")
    else:
        print(f"❌ Over-fit 의심 — IS는 좋지만 OOS Sharpe {delta_sharpe:+.3f}. 디폴트 유지.")
    print("=" * 88)

    # 전체 5년에서도 비교 (참고용)
    print("\n[참고] 전체 5년 결과")
    print(f"{'전략':<25s}  {'ret':>10s}  {'Sharpe':>8s}  {'MDD':>10s}")
    full_baseline = evaluate(ohlcv, {"mult_markup": 1.2})
    full_tuned = evaluate(ohlcv, {"mult_markup": best_mult})
    print(f"{'baseline (mult=1.2)':<25s}  {full_baseline['ret']*100:>+9.2f}%  "
          f"{full_baseline['sharpe']:>8.3f}  {full_baseline['mdd']*100:>+9.2f}%")
    print(f"{f'tuned (mult={best_mult})':<25s}  {full_tuned['ret']*100:>+9.2f}%  "
          f"{full_tuned['sharpe']:>8.3f}  {full_tuned['mdd']*100:>+9.2f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
