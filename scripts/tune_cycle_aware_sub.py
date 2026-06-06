"""cycle_aware 서브 전략 조합 walk-forward 그리드.

후보:
- 추세 (4개): donchian_atr (현재), tsmom, larry_atr, ma_cross
- 평균회귀 (2개): crsi (현재), rsi

총 8 조합 + 베이스라인. IS Sharpe 기준 정렬 → OOS 검증.
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
    print("=" * 100)
    print("cycle_aware 서브 전략 조합 walk-forward (4 trend × 2 MR = 8 조합)")
    print("=" * 100)

    ohlcv = load_ohlcv(symbol="BTCUSDT", interval="1d", lookback_days=1825,
                      cache_dir=ROOT / "data")
    n = len(ohlcv)
    is_ohlcv = ohlcv.iloc[:n // 2]
    oos_ohlcv = ohlcv.iloc[n // 2:]
    print(f"IS  {is_ohlcv.index.min().date()} ~ {is_ohlcv.index.max().date()}")
    print(f"OOS {oos_ohlcv.index.min().date()} ~ {oos_ohlcv.index.max().date()}")

    trend_options = ["donchian_atr", "tsmom", "larry_atr", "ma_cross"]
    mr_options = ["crsi", "rsi"]

    print("\n" + "=" * 100)
    print(f"{'trend':<14s} {'MR':<6s} | "
          f"{'IS ret':>9s} {'IS Sharpe':>10s} {'IS MDD':>9s} | "
          f"{'OOS ret':>9s} {'OOS Sharpe':>11s} {'OOS MDD':>9s} {'OOS trades':>11s}")
    print("-" * 100)

    rows = []
    for trend in trend_options:
        for mr in mr_options:
            params = {"trend_strategy": trend, "mr_strategy": mr}
            is_r = evaluate(is_ohlcv, params)
            oos_r = evaluate(oos_ohlcv, params)
            tag = " ← 현재" if (trend == "donchian_atr" and mr == "crsi") else ""
            rows.append({
                "trend": trend, "mr": mr,
                "is_sharpe": is_r["sharpe"], "is_ret": is_r["ret"], "is_mdd": is_r["mdd"],
                "oos_sharpe": oos_r["sharpe"], "oos_ret": oos_r["ret"],
                "oos_mdd": oos_r["mdd"], "oos_trades": oos_r["trades"],
                "tag": tag,
            })
            print(f"{trend:<14s} {mr:<6s} | "
                  f"{is_r['ret']*100:>+8.2f}% {is_r['sharpe']:>10.3f} {is_r['mdd']*100:>+8.2f}% | "
                  f"{oos_r['ret']*100:>+8.2f}% {oos_r['sharpe']:>11.3f} {oos_r['mdd']*100:>+8.2f}% "
                  f"{oos_r['trades']:>11d}{tag}")

    # IS Sharpe 기준 정렬
    print("\n" + "=" * 100)
    print("IS Sharpe 기준 순위 (높을수록 좋음)")
    print("=" * 100)
    rows.sort(key=lambda r: -r["is_sharpe"])
    print(f"{'rank':<5s} {'trend':<14s} {'MR':<6s} {'IS Sharpe':>10s} {'OOS Sharpe':>11s} {'OOS Δ':>9s}")
    baseline_oos = next(r["oos_sharpe"] for r in rows if r["trend"] == "donchian_atr" and r["mr"] == "crsi")
    for i, r in enumerate(rows, 1):
        delta = r["oos_sharpe"] - baseline_oos
        print(f"{i:<5d} {r['trend']:<14s} {r['mr']:<6s} {r['is_sharpe']:>10.3f} "
              f"{r['oos_sharpe']:>11.3f} {delta:>+8.3f}{r['tag']}")

    # OOS Sharpe 기준 최고
    print("\n" + "=" * 100)
    print("OOS Sharpe 기준 최고 (실제 채택 후보)")
    print("=" * 100)
    rows.sort(key=lambda r: -r["oos_sharpe"])
    print(f"{'rank':<5s} {'trend':<14s} {'MR':<6s} {'OOS Sharpe':>11s} {'OOS ret':>9s} {'OOS MDD':>9s} {'IS-OOS decay':>13s}")
    for i, r in enumerate(rows[:5], 1):
        decay = r["is_sharpe"] - r["oos_sharpe"]
        print(f"{i:<5d} {r['trend']:<14s} {r['mr']:<6s} {r['oos_sharpe']:>11.3f} "
              f"{r['oos_ret']*100:>+8.2f}% {r['oos_mdd']*100:>+8.2f}% {decay:>+12.3f}{r['tag']}")

    # 5년 전체 비교
    print("\n" + "=" * 100)
    print("전체 5년 성과 (참고용)")
    print("=" * 100)
    print(f"{'trend':<14s} {'MR':<6s} {'ret':>10s} {'Sharpe':>8s} {'MDD':>10s} {'trades':>7s}")
    full_rows = []
    for trend in trend_options:
        for mr in mr_options:
            r = evaluate(ohlcv, {"trend_strategy": trend, "mr_strategy": mr})
            full_rows.append({"trend": trend, "mr": mr, **r})
    full_rows.sort(key=lambda r: -r["sharpe"])
    for r in full_rows:
        tag = " ← 현재" if (r["trend"] == "donchian_atr" and r["mr"] == "crsi") else ""
        print(f"{r['trend']:<14s} {r['mr']:<6s} {r['ret']*100:>+9.2f}% {r['sharpe']:>8.3f} "
              f"{r['mdd']*100:>+9.2f}% {r['trades']:>7d}{tag}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
