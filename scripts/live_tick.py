"""Live (Binance Testnet/Mainnet) trading tick.

paper_tick.py 와 같은 구조이지만 실 Binance API 사용.
디폴트는 testnet=True (가짜 돈).

실행:
  로컬: $env:BINANCE_TESTNET_API_KEY='xxx' ; python -X utf8 scripts/live_tick.py
  GHA: .github/workflows/live_trading.yml 에서 secrets로 주입
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.live import run_live_tick  # noqa: E402


DEFAULT_CONFIG = {
    "symbol": "BTCUSDT",
    "interval": "1d",
    "strategy": "cycle_aware",
    "strategy_params": {},
    "testnet": True,                # 기본 = 테스트넷. 실거래 시 False 명시 필요
    "fee_rate": 0.001,              # 표시용 (실제 fee는 Binance가 적용)
    "slippage_rate": 0.0005,
    "lookback_days": 730,
}


def _load_config() -> dict:
    """config/live_trading.yaml 이 있으면 디폴트와 머지."""
    cfg_path = ROOT / "config" / "live_trading.yaml"
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        return {**DEFAULT_CONFIG, **user_cfg}
    return DEFAULT_CONFIG


def main() -> int:
    config = _load_config()
    state_path = ROOT / "data" / "live_state.json"
    dashboard_path = ROOT / "docs" / "live_dashboard.html"
    cache_dir = ROOT / "data"

    mode = "testnet" if config.get("testnet", True) else "MAINNET"
    print(f"[live/{mode}] tick start — strategy={config['strategy']}, symbol={config['symbol']}")
    result = run_live_tick(
        state_path=state_path,
        dashboard_path=dashboard_path,
        config=config,
        cache_dir=cache_dir,
    )

    if result["duplicate_bar"]:
        print(f"[live/{mode}] same bar as last tick ({result['bar_time']}), no trade")
    elif result["trade"]:
        t = result["trade"]
        if t.get("side") == "error":
            print(f"[live/{mode}] ORDER ERROR: code={t['error_code']} {t['error_message']}")
            return 1
        print(f"[live/{mode}] {t['side'].upper()} {t['qty']:.6f} @ ${t['price']:.2f} "
              f"(fee {t['fee']:.6f} {t.get('fee_asset', '')}) "
              f"— signal={result['signal']:.3f}")
    else:
        print(f"[live/{mode}] signal={result['signal']:.3f} — no rebalance needed")

    print(f"[live/{mode}] cash=${result['cash']:.2f}, "
          f"BTC={result['base_qty']:.6f}, "
          f"equity=${result['equity']:.2f}, "
          f"price=${result['price']:.2f}")
    print(f"[live/{mode}] dashboard → {dashboard_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
