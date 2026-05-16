"""스모크 테스트 — 8개 전략이 BTC 데이터로 끝까지 도는지 확인.

빠른 동작 점검용. 정량 검증은 scripts/validate_5y.py 사용.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.backtest import grid_search, run_backtest, run_multi_coin
from src.data import load_ohlcv
from src.strategies import REGISTRY


def main() -> int:
    print("[1/4] BTCUSDT 1d / 365일 데이터 로드...")
    ohlcv = load_ohlcv("BTCUSDT", "1d", lookback_days=365, cache_dir=ROOT / "data")
    print(f"  -> {len(ohlcv)} bars, {ohlcv.index.min().date()} ~ {ohlcv.index.max().date()}")
    assert len(ohlcv) > 200

    print(f"\n[2/4] 등록된 {len(REGISTRY)}개 전략 디폴트 파라미터 백테스트...")
    for name, meta in REGISTRY.items():
        strategy = meta.cls()
        result = run_backtest(ohlcv=ohlcv, strategy=strategy,
                              initial_capital=10_000, fee_rate=0.001, slippage_rate=0.0005)
        m = result.metrics
        print(f"  - {name:22s} ret={m['total_return']*100:+7.2f}%  "
              f"Sharpe={m['sharpe']:6.2f}  MDD={m['max_drawdown']*100:+7.2f}%  "
              f"trades={m['num_trades']:3d}")

    print("\n[3/4] 그리드 서치 (CRSI lower x trend_period)...")
    opt = grid_search(
        ohlcv=ohlcv, strategy_name="crsi",
        grid={"lower": [10, 15, 20, 25], "trend_period": [100, 150, 200]},
        metric="sharpe",
    )
    print(f"  -> best={opt.best_params}, 조합 수={len(opt.table)}")
    assert len(opt.table) == 12

    print("\n[4/4] 멀티 코인 비교 (BTC/ETH/SOL, CRSI 디폴트)...")
    mc = run_multi_coin(
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        strategy_name="crsi", strategy_params={},
        interval="1d", lookback_days=365, cache_dir=str(ROOT / "data"),
    )
    print(mc.summary[["symbol", "total_return", "sharpe", "max_drawdown",
                      "num_trades", "buy_and_hold"]].to_string(index=False))
    assert not mc.summary.empty

    print("\n[OK] 모든 컴포넌트 정상 동작.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
