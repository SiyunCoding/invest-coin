"""페이퍼 트레이딩 한 tick 실행.

매일 한 번씩 호출되어:
  1. 최신 Binance OHLCV fetch
  2. cycle_aware 신호 계산
  3. 가상 포트폴리오 리밸런싱
  4. data/paper_state.json 업데이트
  5. docs/dashboard.html 재생성

GitHub Actions (.github/workflows/paper_trading.yml)가 매일 UTC 00:30에 호출.
로컬에서도 그냥 실행 가능: python -X utf8 scripts/paper_tick.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.paper import run_tick  # noqa: E402


DEFAULT_CONFIG = {
    "symbol": "BTCUSDT",
    "interval": "1d",
    "strategy": "cycle_aware",
    "strategy_params": {},  # 디폴트 사용 (apply_cycle=True for BTC)
    "initial_capital": 100_000.0,
    "fee_rate": 0.001,
    "slippage_rate": 0.0005,
    "lookback_days": 730,  # cycle_aware는 SMA200 + ATR percentile 252 워밍업 필요
}


def _load_config() -> dict:
    cfg_path = ROOT / "config" / "paper_trading.yaml"
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        return {**DEFAULT_CONFIG, **user_cfg}
    return DEFAULT_CONFIG


def main() -> int:
    config = _load_config()
    state_path = ROOT / "data" / "paper_state.json"
    dashboard_path = ROOT / "docs" / "dashboard.html"
    cache_dir = ROOT / "data"

    print(f"[paper] tick start — strategy={config['strategy']}, symbol={config['symbol']}")
    result = run_tick(
        state_path=state_path,
        dashboard_path=dashboard_path,
        config=config,
        cache_dir=cache_dir,
    )

    if result["duplicate_bar"]:
        print(f"[paper] same bar as last tick ({result['bar_time']}), no trade")
    elif result["trade"]:
        t = result["trade"]
        print(f"[paper] {t['side'].upper()} {t['qty']:.6f} @ ${t['price']:.2f} "
              f"(fee ${t['fee']:.2f}) — signal={result['signal']:.3f}")
    else:
        print(f"[paper] signal={result['signal']:.3f} — no rebalance needed")

    print(f"[paper] equity=${result['equity']:.2f}, price=${result['price']:.2f}")
    print(f"[paper] dashboard updated → {dashboard_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
