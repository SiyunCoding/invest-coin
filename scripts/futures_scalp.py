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
    print(f"[futures/{mode}] tick start — leverage={config['leverage']}x, "
          f"margin=${config['margin_usdt']}, RSI>{config['rsi_threshold']} SHORT")

    result = run_futures_tick(state_path=state_path, config=config)

    print(f"[futures/{mode}] tick #{result['tick_count']} — "
          f"symbols={result['total_symbols']}, "
          f"balance=${result['balance']:,.2f}, "
          f"open_positions={result['open_positions']}, "
          f"entries={result['new_entries']}, "
          f"closures={result['closures']}, "
          f"errors={result['errors']}, "
          f"rsi_candidates={result['rsi_candidates']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
