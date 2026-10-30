"""Live (Binance Testnet/Mainnet) Trend Rotation tick.

매일 한 번 호출 → BTC 슬리브 + 월간 알트 유니버스 Donchian 앙상블 → 시장가 리밸런스 → state/dashboard/Telegram.
디폴트는 testnet=True (가짜 돈). config/live_trading.yaml 로 override (mainnet 전환 포함).

실행:
  로컬: $env:BINANCE_TESTNET_API_KEY='xxx' ; python -X utf8 scripts/live_tick.py
  GHA: .github/workflows/live_trading.yml 에서 secrets로 주입 (self-hosted runner)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.live import run_portfolio_tick  # noqa: E402


DEFAULT_CONFIG = {
    "strategy": "trend_rotation",
    "testnet": True,                 # 기본 = 테스트넷. 실거래 시 False 명시 필요
    "lookback_days": 1000,           # 360일 Donchian + 90일 변동성 + 경로 의존 여유
    "candidate_pool": 40,            # 유니버스 후보: 24h 거래대금 상위 N 개만 30일 중위값 계산
    "min_equity_for_alts": 3000,     # 이 미만이면 알트 슬리브 끄고 BTC 단독 (최소 주문금액 $5 대응: 최소 슬롯 ~0.33%)
    "trend_rotation": {},            # src.portfolio.TrendRotationConfig 필드 override
    "safety": {
        "daily_loss_limit_pct": 0.05,   # 직전 tick 대비 -5% 이하면 매수 중지 (매도는 허용)
        "halt_file": ".halt",           # 이 파일 존재 시 모든 주문 중지
    },
}


def _load_config() -> dict:
    """config/live_trading.yaml 이 있으면 디폴트와 머지 (safety/trend_rotation 은 한 단계 깊이까지)."""
    cfg_path = ROOT / "config" / "live_trading.yaml"
    config = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_CONFIG.items()}
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        for k, v in user_cfg.items():
            if isinstance(v, dict) and isinstance(config.get(k), dict):
                config[k].update(v)
            else:
                config[k] = v
    return config


def main() -> int:
    config = _load_config()
    state_path = ROOT / "data" / "live_state.json"
    dashboard_path = ROOT / "docs" / "live_dashboard.html"
    # 러너 작업 폴더는 매 실행 git clean 되므로 캐시/백업은 홈 아래에 (재다운로드·백업 소실 방지)
    home = Path(os.environ.get("INVEST_COIN_HOME", Path.home() / ".invest-coin"))

    mode = "testnet" if config.get("testnet", True) else "MAINNET"
    print(f"[live/{mode}] tick start — strategy={config['strategy']}")
    result = run_portfolio_tick(state_path=state_path, dashboard_path=dashboard_path, config=config,
                                cache_dir=home / "cache", root_dir=ROOT, backup_dir=home / "backups")

    print(f"[live/{mode}] bar={result['bar_time']} equity=${result['equity']:,.2f} "
          f"exposure={result['exposure']*100:.1f}% nav={result['nav']:.4f}")
    print(f"[live/{mode}] universe={result['universe']} dropped={result['dropped']} "
          f"untradable={result['untradable']}")
    for t in result["trades"]:
        if t.get("side") == "error":
            print(f"[live/{mode}] ORDER ERROR {t.get('symbol')} {t.get('attempted')}: "
                  f"{t.get('error_code')} {t.get('error_message')}")
        else:
            print(f"[live/{mode}] {t['side'].upper()} {t['symbol']} {t['qty']:.6f} @ {t['price']:.4f} "
                  f"(${t['value']:,.2f})")
    if result["reasons"]:
        print(f"[live/{mode}] SAFETY: {result['reasons']}")
    if result["fetch_failed"]:
        print(f"[live/{mode}] data fetch failed (보유 유지): {result['fetch_failed']}")
    if result["external_flow"]:
        print(f"[live/{mode}] external flow detected ${result['external_flow']:+,.2f}")
    print(f"[live/{mode}] dashboard → {dashboard_path.relative_to(ROOT)}")
    # 주문 오류는 Telegram 으로 알리고 0 반환 — 실패로 끝내면 워크플로우가 state 커밋을 건너뛰어 기록이 소실됨
    return 0


if __name__ == "__main__":
    sys.exit(main())
