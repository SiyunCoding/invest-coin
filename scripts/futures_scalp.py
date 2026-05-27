"""Futures 50x scalping tick (RSI 5m > 70 → SHORT + TP 자동 청산).

실행:
  로컬: $env:BINANCE_FUTURES_TESTNET_API_KEY='xxx' ; python -X utf8 scripts/futures_scalp.py
  GHA: .github/workflows/futures_scalping.yml (5분 cron, self-hosted runner)
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.live import run_futures_tick  # noqa: E402


def _load_config() -> dict:
    cfg_path = ROOT / "config" / "futures_scalping.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(f"config not found: {cfg_path}")
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> int:
    config = _load_config()
    state_path = ROOT / "data" / "futures_state.json"
    mode = "demo" if config.get("demo", True) else "MAINNET"
    print(f"[futures/{mode}] tick start — symbol={config['symbol']}, "
          f"leverage={config['leverage']}x, margin=${config['margin_usdt']}")

    result = run_futures_tick(state_path=state_path, config=config)

    print(f"[futures/{mode}] RSI(5m)={result['rsi']:.2f}, "
          f"price=${result['price']:,.2f}, "
          f"balance=${result['balance']:,.2f}, "
          f"position_amt={result['position_amt']:.6f}")
    if result["new_trade"]:
        t = result["new_trade"]
        print(f"[futures/{mode}] {t['side']} ENTRY "
              f"qty={t['qty']:.6f} @ ${t['entry_price']:,.2f}, "
              f"TP @ ${t['tp_stop_price']:,.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
