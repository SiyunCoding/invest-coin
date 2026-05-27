"""Futures Scalper — 무한 루프 데몬 (systemd로 띄움).

Oracle Cloud 서버에서 systemd 서비스로 띄워서 정확히 5분마다 tick.
GHA cron의 부정확성과 startup overhead 제거.

흐름:
  - 5분마다 run_futures_tick 호출
  - 에러 발생 시 Telegram으로 알림 + 다음 사이클 계속
  - SIGTERM/SIGINT 받으면 graceful shutdown + 종료 알림

설치 (Oracle 서버):
  ~/invest-coin 디렉토리에 클론 + .env 생성 + scalper.service systemd 등록.
  자세한 단계는 README "Futures Scalper 데몬 설치" 참고.
"""
from __future__ import annotations

import os
import signal
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.live import run_futures_tick  # noqa: E402
from src.notifier import send_telegram_message  # noqa: E402

SLEEP_SECONDS = int(os.environ.get("SCALPER_SLEEP_SECONDS", "300"))  # 디폴트 5분

_running = True


def _shutdown(signum, frame):
    global _running
    _running = False
    print(f"[scalper] shutdown signal {signum} received, stopping after current tick")


signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT, _shutdown)


def _load_config() -> dict:
    cfg_path = ROOT / "config" / "futures_scalping.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> int:
    config = _load_config()
    state_path = ROOT / "data" / "futures_state.json"

    mode = "demo" if config.get("demo", True) else "MAINNET"
    lev_min = config.get("leverage_min", config.get("leverage", 50))
    lev_max = config.get("leverage_max", config.get("leverage", 50))
    boot_msg = (
        f"🟢 *선물 스캘퍼 시작* ({mode})\n"
        f"• 종목: USDT 무기한 선물 중 max 레버리지 `{lev_min}~{lev_max}x` 코인만\n"
        f"• 마진 모드: `{config['margin_type']}`\n"
        f"• 마진/회: `${config['margin_usdt']}` / 익절: 마진 `{int(config['tp_profit_pct']*100)}%`\n"
        f"• 신호: RSI(5m) > `{config['rsi_threshold']}` → SHORT\n"
        f"• 동시 포지션: 허용 (코인별 독립)\n"
        f"• 주기: `{SLEEP_SECONDS}`초 · 헬스체크: `{config.get('heartbeat_every_n_ticks', 12)}` tick마다"
    )
    send_telegram_message(boot_msg)
    print(f"[scalper/{mode}] started, sleep={SLEEP_SECONDS}s")

    tick_count = 0
    while _running:
        tick_count += 1
        t0 = time.time()
        try:
            result = run_futures_tick(state_path=state_path, config=config)
            ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
            print(
                f"[scalper/{mode}] {ts} tick #{tick_count} OK — "
                f"symbols={result['total_symbols']}, "
                f"balance=${result['balance']:,.2f}, "
                f"positions={result['open_positions']}, "
                f"entries={result['new_entries']}, "
                f"closures={result['closures']}, "
                f"errors={result['errors']}"
            )
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[scalper/{mode}] ERROR on tick #{tick_count}: {e}\n{tb}", file=sys.stderr)
            try:
                # 너무 길면 Telegram이 자름 — 마지막 500자만
                err_msg = f"⚠️ *선물 스캘퍼 에러* (tick #{tick_count})\n```\n{str(e)[:500]}\n```"
                send_telegram_message(err_msg)
            except Exception:
                pass

        # sleep 중간에 SIGTERM 받으면 빨리 빠져나오게
        elapsed = time.time() - t0
        sleep_remaining = max(0.0, SLEEP_SECONDS - elapsed)
        slept = 0.0
        while _running and slept < sleep_remaining:
            time.sleep(min(1.0, sleep_remaining - slept))
            slept += 1.0

    try:
        send_telegram_message(f"🔴 *선물 스캘퍼 중지* ({mode}) · tick={tick_count}")
    except Exception:
        pass
    print(f"[scalper/{mode}] stopped after {tick_count} ticks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
