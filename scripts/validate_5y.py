"""5년치 데이터로 multi-regime walk-forward 결정타 검증.

기간 분할 (대략):
  Regime 1 (2021-05 ~ 2022-11): 2021 상승 -> 2022 폭락 (LUNA/FTX)
  Regime 2 (2022-11 ~ 2024-05): 2022 바닥 -> 2024 반감기 상승
  Regime 3 (2024-05 ~ 2026-05): 2024-25 변동성 + 2025-26 횡보
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


SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
LOOKBACK_DAYS = 1825  # 5년
INITIAL_CAPITAL = 10_000.0
FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0005


def _pct(x):
    return "    -   " if pd.isna(x) else f"{x*100:+7.2f}%"


def _num(x, fmt="{:6.2f}"):
    return "  -  " if pd.isna(x) else fmt.format(x)


def _evaluate(ohlcv, name, params=None):
    if ohlcv.empty or len(ohlcv) < 100:
        return None
    meta = REGISTRY[name]
    strategy = meta.cls() if params is None else meta.cls(**params)
    try:
        return run_backtest(
            ohlcv=ohlcv, strategy=strategy,
            initial_capital=INITIAL_CAPITAL,
            fee_rate=FEE_RATE, slippage_rate=SLIPPAGE_RATE,
        ).metrics
    except Exception as e:
        return {"error": str(e)}


def main() -> int:
    print("=" * 90)
    print(f"5년치 데이터 다운로드 (lookback={LOOKBACK_DAYS}일)")
    print("=" * 90)

    ohlcvs = {}
    for sym in SYMBOLS:
        df = load_ohlcv(sym, "1d", lookback_days=LOOKBACK_DAYS, cache_dir=ROOT / "data")
        if df.empty:
            print(f"  {sym}: 데이터 없음")
            continue
        bh = float(df["close"].iloc[-1] / df["close"].iloc[0] - 1)
        ohlcvs[sym] = df
        print(f"  {sym}: {len(df)} bars, {df.index.min().date()} ~ {df.index.max().date()}, "
              f"B&H = {_pct(bh)}")

    if "BTCUSDT" not in ohlcvs:
        print("BTC 데이터 없음, 종료")
        return 1

    # 5년 전체 통합 평가
    print("\n\n" + "#" * 90)
    print("# 5년 통합 평가 (3 코인 평균, 디폴트 파라미터)")
    print("#" * 90)

    rows = []
    for sym, ohlcv in ohlcvs.items():
        bh = float(ohlcv["close"].iloc[-1] / ohlcv["close"].iloc[0] - 1)
        for name in REGISTRY:
            m = _evaluate(ohlcv, name)
            if m and "error" not in m:
                rows.append({
                    "symbol": sym, "strategy": name,
                    "total_return": m["total_return"],
                    "sharpe": m["sharpe"],
                    "max_drawdown": m["max_drawdown"],
                    "num_trades": m["num_trades"],
                    "vs_bh": m["total_return"] - bh,
                })
    df = pd.DataFrame(rows)
    summary = df.groupby("strategy").agg(
        avg_return=("total_return", "mean"),
        avg_sharpe=("sharpe", "mean"),
        avg_mdd=("max_drawdown", "mean"),
        avg_vs_bh=("vs_bh", "mean"),
        avg_trades=("num_trades", "mean"),
    ).sort_values("avg_sharpe", ascending=False)
    print(f"\n  {'strategy':22s} {'avg_ret':>10s} {'Sharpe':>8s} "
          f"{'MDD':>10s} {'vs B&H':>10s} {'trades':>8s}")
    for name, row in summary.iterrows():
        print(f"  {name:22s} {_pct(row['avg_return'])} "
              f"{_num(row['avg_sharpe'], '{:8.2f}')} {_pct(row['avg_mdd'])} "
              f"{_pct(row['avg_vs_bh'])} {row['avg_trades']:8.1f}")

    # BTC를 3등분해서 regime별 분석
    btc = ohlcvs["BTCUSDT"]
    n = len(btc)
    b1 = n // 3
    b2 = 2 * n // 3
    regimes = {
        "R1 (2021-22, LUNA/FTX 폭락)": btc.iloc[:b1],
        "R2 (2022-24, 회복+반감기)": btc.iloc[b1:b2],
        "R3 (2024-26, 변동성+횡보)": btc.iloc[b2:],
    }
    print("\n\n" + "#" * 90)
    print("# Regime별 분석 (BTC 5년 → 3등분)")
    print("#" * 90)
    for label, period in regimes.items():
        bh = float(period["close"].iloc[-1] / period["close"].iloc[0] - 1)
        print(f"\n--- {label} ({period.index.min().date()} ~ {period.index.max().date()}, "
              f"B&H {_pct(bh)}) ---")
        regime_rows = []
        for name in REGISTRY:
            m = _evaluate(period, name)
            if m and "error" not in m:
                regime_rows.append({
                    "strategy": name,
                    "total_return": m["total_return"],
                    "sharpe": m["sharpe"],
                    "max_drawdown": m["max_drawdown"],
                    "num_trades": m["num_trades"],
                })
        regime_rows.sort(key=lambda r: r["sharpe"] if not pd.isna(r["sharpe"]) else -999,
                         reverse=True)
        for r in regime_rows:
            print(f"  {r['strategy']:22s} ret={_pct(r['total_return'])}  "
                  f"Sharpe={_num(r['sharpe'])}  MDD={_pct(r['max_drawdown'])}  "
                  f"trades={r['num_trades']:>3d}")

    # 가장 robust한 전략: 모든 regime에서 양수 Sharpe + 작은 MDD
    print("\n\n" + "#" * 90)
    print("# Robust 점수 (3 regime 모두 Sharpe>0인 전략 찾기)")
    print("#" * 90)

    robust_scores = {}
    for name in REGISTRY:
        sharpes = []
        rets = []
        mdds = []
        for period in regimes.values():
            m = _evaluate(period, name)
            if m and "error" not in m and not pd.isna(m["sharpe"]):
                sharpes.append(m["sharpe"])
                rets.append(m["total_return"])
                mdds.append(m["max_drawdown"])
        if len(sharpes) == len(regimes):
            robust_scores[name] = {
                "min_sharpe": min(sharpes),
                "avg_sharpe": sum(sharpes) / len(sharpes),
                "min_ret": min(rets),
                "avg_ret": sum(rets) / len(rets),
                "max_mdd": min(mdds),
                "positive_regimes": sum(1 for s in sharpes if s > 0),
            }

    # min_sharpe 내림차순
    sorted_robust = sorted(robust_scores.items(), key=lambda kv: kv[1]["min_sharpe"],
                          reverse=True)
    print(f"\n  {'strategy':22s} {'min Sharpe':>11s} {'avg Sharpe':>11s} "
          f"{'min ret':>10s} {'max MDD':>10s} {'+ regimes':>10s}")
    for name, s in sorted_robust:
        print(f"  {name:22s} {_num(s['min_sharpe'], '{:11.2f}')} "
              f"{_num(s['avg_sharpe'], '{:11.2f}')} {_pct(s['min_ret'])} "
              f"{_pct(s['max_mdd'])} {s['positive_regimes']:>5d}/3")

    print("\n" + "=" * 90)
    print("최종 결정타: min Sharpe(3 regime 모두 견디는 능력) + max MDD가 가장 작은 전략")
    print("=" * 90)

    return 0


if __name__ == "__main__":
    sys.exit(main())
