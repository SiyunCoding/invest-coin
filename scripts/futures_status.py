"""Futures scalper 현재 상태 요약. Oracle 서버에서 ad-hoc으로 호출."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "futures_state.json"


def main() -> int:
    if not STATE_PATH.exists():
        print(f"[!] state 파일 없음: {STATE_PATH}")
        return 1

    s = json.loads(STATE_PATH.read_text(encoding="utf-8"))

    initial = float(s.get("initial_balance", 0))
    hist = s.get("history", [])
    last_bal = float(hist[-1]["balance"]) if hist else initial
    pnl = last_bal - initial
    pnl_pct = pnl / initial * 100 if initial > 0 else 0.0
    peak = float(s.get("peak_balance", initial))
    mdd = (last_bal / peak - 1) * 100 if peak > 0 else 0.0

    trades = s.get("trades", [])
    entries = sum(1 for t in trades if t.get("type") == "entry")
    closes = sum(1 for t in trades if t.get("type") == "closure")
    errors = sum(1 for t in trades if t.get("type") == "error")
    positions = s.get("positions", {})

    print(f"=== Futures Scalper ({s.get('mode', '?')}) ===")
    print(f"시작일:       {s.get('started_at', '?')[:19]}")
    print(f"시작 자본:    ${initial:,.2f}")
    print(f"현재 잔고:    ${last_bal:,.2f}")
    print(f"수익:         ${pnl:+,.2f} ({pnl_pct:+.3f}%)")
    print(f"MDD:          {mdd:+.3f}%")
    print(f"추적 심볼:    {len(s.get('symbols_cache', []))}")
    print(f"tick 수:      {s.get('tick_count', 0)}")
    print(f"누적 거래:    진입 {entries} / 청산 {closes} / 에러 {errors}")
    print(f"오픈 포지션: {len(positions)}")
    if positions:
        for sym, p in list(positions.items())[:10]:
            print(f"  - {sym} @ ${float(p['entry_price']):,.4f} (TP ${float(p.get('tp_stop_price', 0)):,.4f})")
        if len(positions) > 10:
            print(f"  ... 외 {len(positions) - 10}개")

    # 최근 거래 5건
    if trades:
        print()
        print("=== 최근 거래 5건 ===")
        for t in trades[-5:]:
            tp = t.get("type", "?")
            sym = t.get("symbol", "?")
            time_str = t.get("time", "?")[:19]
            if tp == "entry":
                print(f"  [{time_str}] ENTRY  {sym} @ ${float(t.get('entry_price', 0)):,.4f} (lev {t.get('leverage')}x)")
            elif tp == "closure":
                print(f"  [{time_str}] CLOSE  {sym}")
            elif tp == "error":
                print(f"  [{time_str}] ERROR  {sym} code={t.get('error_code')} {str(t.get('error_message', ''))[:60]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
