"""모든 전략 BTC 3년 그리드 서치 + Walk-forward 검증 + 최종 비교 리포트.

단계
1. BTC 3년 데이터로 5개 전략 각각 그리드 서치 (Sharpe 기준)
2. Walk-forward: 처음 50%로 튜닝 -> 뒤 50%에서 검증 (over-fitting 점검)
3. 튜닝된 파라미터로 BTC/ETH/SOL에서 최종 비교
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest import grid_search, run_backtest
from src.data import load_ohlcv
from src.strategies import REGISTRY


SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
LOOKBACK_DAYS = 1095
INITIAL_CAPITAL = 10_000.0
FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0005

GRIDS = {
    "volatility_breakout": {
        "k": [round(0.1 + 0.05 * i, 2) for i in range(28)],  # 0.10 ~ 1.45
    },
    "ma_cross": {
        "fast": [3, 5, 7, 10, 15, 20, 30, 40],
        "slow": [20, 30, 40, 60, 80, 100, 150, 200],
    },
    "rsi": {
        "period": [7, 10, 14, 20, 28],
        "oversold": [15, 20, 25, 30, 35],
        "overbought": [60, 65, 70, 75, 80],
    },
    "crsi": {
        "lower": [5, 10, 15, 20, 25],
        "trend_period": [50, 100, 150, 200],
    },
    "donchian_atr": {
        "lookback": [10, 15, 20, 30, 50, 80, 120],
        "atr_mult": [2.0, 3.0, 4.0, 5.0, 6.0, 8.0],
    },
}


def _pct(x):
    return "    -   " if pd.isna(x) else f"{x*100:+7.2f}%"


def _num(x, fmt="{:6.2f}"):
    return "  -  " if pd.isna(x) else fmt.format(x)


def _coerce_params(strategy_name: str, raw: dict) -> dict:
    meta = REGISTRY[strategy_name]
    out = {}
    for spec in meta.params:
        if spec.name in raw:
            v = raw[spec.name]
            out[spec.name] = int(round(v)) if spec.kind == "int" else float(v)
    return out


def _tune(ohlcv: pd.DataFrame, strategy_name: str, metric: str = "sharpe") -> dict:
    opt = grid_search(
        ohlcv=ohlcv, strategy_name=strategy_name,
        grid=GRIDS[strategy_name], metric=metric,
        initial_capital=INITIAL_CAPITAL,
        fee_rate=FEE_RATE, slippage_rate=SLIPPAGE_RATE,
    )
    return _coerce_params(strategy_name, opt.best_params)


def _evaluate(ohlcv: pd.DataFrame, strategy_name: str, params: dict) -> dict:
    meta = REGISTRY[strategy_name]
    strategy = meta.cls(**params)
    result = run_backtest(
        ohlcv=ohlcv, strategy=strategy,
        initial_capital=INITIAL_CAPITAL,
        fee_rate=FEE_RATE, slippage_rate=SLIPPAGE_RATE,
    )
    return result.metrics


def step1_grid_search_all(btc: pd.DataFrame) -> dict:
    print("\n" + "#" * 90)
    print("# Step 1. BTC 3년 데이터로 모든 전략 그리드 서치 (Sharpe 기준)")
    print("#" * 90)
    tuned = {}
    for name in REGISTRY:
        n_combos = 1
        for v in GRIDS[name].values():
            n_combos *= len(v)
        print(f"\n[{name}] grid={GRIDS[name]} -> {n_combos} 조합 탐색 중...")
        params = _tune(btc, name)
        metrics = _evaluate(btc, name, params)
        tuned[name] = params
        bh = float(btc["close"].iloc[-1] / btc["close"].iloc[0] - 1)
        print(f"  Best params: {params}")
        print(f"  in-sample: ret={_pct(metrics['total_return'])}  "
              f"Sharpe={_num(metrics['sharpe'])}  "
              f"MDD={_pct(metrics['max_drawdown'])}  "
              f"trades={metrics['num_trades']}  "
              f"(BTC B&H {_pct(bh)})")
    return tuned


def step2_walk_forward(btc: pd.DataFrame) -> pd.DataFrame:
    """전반부 50%로 튜닝, 후반부 50%에서 검증."""
    print("\n\n" + "#" * 90)
    print("# Step 2. Walk-forward: in-sample 튜닝 -> out-of-sample 검증")
    print("#" * 90)
    n = len(btc)
    cut = n // 2
    in_sample = btc.iloc[:cut]
    out_sample = btc.iloc[cut:]
    print(f"  in-sample : {in_sample.index.min()} ~ {in_sample.index.max()}  ({len(in_sample)} bars)")
    print(f"  out-sample: {out_sample.index.min()} ~ {out_sample.index.max()}  ({len(out_sample)} bars)")

    bh_in = float(in_sample["close"].iloc[-1] / in_sample["close"].iloc[0] - 1)
    bh_out = float(out_sample["close"].iloc[-1] / out_sample["close"].iloc[0] - 1)
    print(f"  in-sample B&H : {_pct(bh_in)}")
    print(f"  out-sample B&H: {_pct(bh_out)}")

    rows = []
    for name in REGISTRY:
        try:
            params_in = _tune(in_sample, name)
        except Exception as e:
            print(f"  [{name}] 튜닝 실패: {e}")
            continue
        m_in = _evaluate(in_sample, name, params_in)
        try:
            m_out = _evaluate(out_sample, name, params_in)
        except Exception as e:
            m_out = {"total_return": float("nan"), "sharpe": float("nan"),
                     "max_drawdown": float("nan"), "num_trades": 0}
            print(f"  [{name}] OOS 실패: {e}")
        rows.append({
            "strategy": name,
            "params": params_in,
            "in_ret": m_in["total_return"],
            "in_sharpe": m_in["sharpe"],
            "in_mdd": m_in["max_drawdown"],
            "out_ret": m_out["total_return"],
            "out_sharpe": m_out["sharpe"],
            "out_mdd": m_out["max_drawdown"],
            "out_trades": m_out["num_trades"],
            "ret_decay": m_in["total_return"] - m_out["total_return"],
        })

    print(f"\n  {'strategy':22s} {'IS ret':>10s} {'OOS ret':>10s} {'decay':>10s} "
          f"{'IS Sharpe':>10s} {'OOS Sharpe':>11s} {'OOS MDD':>10s} {'OOS trades':>10s}")
    for r in rows:
        print(f"  {r['strategy']:22s} {_pct(r['in_ret'])} {_pct(r['out_ret'])} "
              f"{_pct(r['ret_decay'])} {_num(r['in_sharpe'], '{:10.2f}')} "
              f"{_num(r['out_sharpe'], '{:11.2f}')} {_pct(r['out_mdd'])} "
              f"{r['out_trades']:>10d}")
    return pd.DataFrame(rows)


def step3_final_comparison(tuned: dict) -> pd.DataFrame:
    print("\n\n" + "#" * 90)
    print("# Step 3. 튜닝된 파라미터로 BTC/ETH/SOL 최종 비교 (3년)")
    print("#" * 90)
    rows = []
    for symbol in SYMBOLS:
        ohlcv = load_ohlcv(symbol, "1d", lookback_days=LOOKBACK_DAYS,
                           cache_dir=ROOT / "data")
        if ohlcv.empty:
            continue
        bh = float(ohlcv["close"].iloc[-1] / ohlcv["close"].iloc[0] - 1)
        print(f"\n--- {symbol} (B&H {_pct(bh)}) ---")
        sub_rows = []
        for name, params in tuned.items():
            m = _evaluate(ohlcv, name, params)
            sub_rows.append({
                "symbol": symbol, "strategy": name,
                "total_return": m["total_return"],
                "sharpe": m["sharpe"],
                "max_drawdown": m["max_drawdown"],
                "num_trades": m["num_trades"],
                "vs_bh": m["total_return"] - bh,
            })
        sub_rows.sort(key=lambda r: r["total_return"], reverse=True)
        for r in sub_rows:
            print(f"  {r['strategy']:22s} ret={_pct(r['total_return'])}  "
                  f"vs B&H={_pct(r['vs_bh'])}  Sharpe={_num(r['sharpe'])}  "
                  f"MDD={_pct(r['max_drawdown'])}  trades={r['num_trades']:>3d}")
        rows.extend(sub_rows)

    df = pd.DataFrame(rows)
    print("\n\n" + "=" * 90)
    print("3 코인 평균 (튜닝된 파라미터)")
    print("=" * 90)
    summary = df.groupby("strategy").agg(
        avg_return=("total_return", "mean"),
        avg_sharpe=("sharpe", "mean"),
        avg_mdd=("max_drawdown", "mean"),
        avg_vs_bh=("vs_bh", "mean"),
        avg_trades=("num_trades", "mean"),
    ).reindex(list(REGISTRY))
    print(f"  {'strategy':22s} {'avg_ret':>10s} {'Sharpe':>8s} "
          f"{'MDD':>10s} {'vs B&H':>10s} {'trades':>8s}")
    for name, row in summary.iterrows():
        print(f"  {name:22s} {_pct(row['avg_return'])} "
              f"{_num(row['avg_sharpe'], '{:8.2f}')} {_pct(row['avg_mdd'])} "
              f"{_pct(row['avg_vs_bh'])} {row['avg_trades']:8.1f}")
    return df


def main() -> int:
    btc = load_ohlcv("BTCUSDT", "1d", lookback_days=LOOKBACK_DAYS,
                     cache_dir=ROOT / "data")
    print(f"BTC 데이터: {btc.index.min()} ~ {btc.index.max()} ({len(btc)} bars)")

    tuned = step1_grid_search_all(btc)
    wf = step2_walk_forward(btc)
    final = step3_final_comparison(tuned)

    print("\n\n" + "#" * 90)
    print("# 최종 튜닝된 파라미터 (BTC 3년 in-sample 기준)")
    print("#" * 90)
    for name, params in tuned.items():
        print(f"  {name:22s} {params}")

    # WF 결과를 robust 지표로 사용
    print("\n\n" + "#" * 90)
    print("# Walk-forward 후 OOS 기준 robust 순위")
    print("#" * 90)
    if not wf.empty:
        wf_sorted = wf.sort_values("out_sharpe", ascending=False)
        for _, r in wf_sorted.iterrows():
            print(f"  {r['strategy']:22s} OOS Sharpe={_num(r['out_sharpe'])}  "
                  f"OOS ret={_pct(r['out_ret'])}  IS->OOS decay={_pct(r['ret_decay'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())