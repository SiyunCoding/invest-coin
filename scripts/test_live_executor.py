"""Live executor 통합 테스트 — Binance Testnet에 실 주문 발생.

테스트 시나리오:
  1. 25% 매수
  2. 50%로 추가 매수
  3. 30%로 부분 매도
  4. 0%로 전량 매도
  5. 0%에서 0% 요청 → 스킵
  6. tiny target (사용자 자산 1% 미만 변동) → 스킵 (hysteresis)
  7. Cleanup: 다시 0%로 정리

각 시나리오마다 잔고 before/after, 거래 응답, 검증 결과를 stdout + markdown으로 기록.

⚠️ 실 Binance Testnet API 호출. 잔고 변동됨. (가짜 돈이지만)
실행:
  로컬: $env:BINANCE_TESTNET_API_KEY = '...' ; python -X utf8 scripts/test_live_executor.py
  GHA:  .github/workflows/test_executor.yml 수동 트리거
"""
from __future__ import annotations

import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.live.client import get_client  # noqa: E402
from src.live.executor import (  # noqa: E402
    get_balances,
    get_current_price,
    get_symbol_filters,
    rebalance_to_target,
    split_symbol,
)


SYMBOL = "BTCUSDT"
SETTLE_SLEEP = 1.5  # 거래 후 거래소 잔고 반영 대기


class TestReport:
    def __init__(self):
        self.lines = []
        self.results = []

    def write(self, line: str = ""):
        print(line)
        self.lines.append(line)

    def record(self, name: str, ok: bool, expected: str, actual: str, note: str = ""):
        self.results.append({"name": name, "ok": ok, "expected": expected, "actual": actual, "note": note})

    def md(self) -> str:
        passed = sum(1 for r in self.results if r["ok"])
        total = len(self.results)
        summary = [
            f"# Live Executor 통합 테스트 결과",
            "",
            f"실행: `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}`",
            f"결과: **{passed}/{total} 통과**",
            "",
            "## 시나리오 결과",
            "",
            "| # | 시나리오 | Expected | Actual | 결과 |",
            "|---|---|---|---|---|",
        ]
        for i, r in enumerate(self.results, 1):
            icon = "✅" if r["ok"] else "❌"
            summary.append(f"| {i} | {r['name']} | {r['expected']} | {r['actual']} | {icon} |")
        summary.extend([
            "",
            "## 상세 로그",
            "",
            "```",
            *self.lines,
            "```",
        ])
        return "\n".join(summary)


def fmt_balance(base_qty, quote_qty, price) -> str:
    equity = quote_qty + base_qty * price
    return f"BTC={base_qty:.8f}, USDT={quote_qty:,.4f}, price=${price:,.2f}, equity=${equity:,.2f}"


def run_scenario(report, client, name: str, target_weight: float,
                 expected_side: str, min_rebalance_frac: float = 0.01):
    """한 시나리오 실행. expected_side ∈ {'buy', 'sell', 'skip'}."""
    base, quote = split_symbol(SYMBOL)
    report.write("")
    report.write(f"=== {name} ===")
    report.write(f"  target_weight = {target_weight}, min_rebalance_frac = {min_rebalance_frac}")

    before_base, before_quote = get_balances(client, base, quote)
    before_price = get_current_price(client, SYMBOL)
    report.write(f"  Before: {fmt_balance(before_base, before_quote, before_price)}")

    try:
        trade = rebalance_to_target(client, SYMBOL, target_weight, min_rebalance_frac=min_rebalance_frac)
    except Exception as e:
        report.write(f"  ❌ EXCEPTION: {type(e).__name__}: {e}")
        report.write(f"  Traceback: {traceback.format_exc()}")
        actual = f"exception ({type(e).__name__})"
        report.record(name, False, expected_side, actual, str(e))
        return

    time.sleep(SETTLE_SLEEP)

    after_base, after_quote = get_balances(client, base, quote)
    after_price = get_current_price(client, SYMBOL)

    if trade is None:
        actual = "skip"
        report.write(f"  Trade: SKIPPED (rebalance not needed)")
    else:
        actual = trade.get("side", "?")
        report.write(
            f"  Trade: {actual.upper()} qty={trade['qty']:.8f} @ ${trade['price']:,.4f}"
        )
        report.write(
            f"         value=${trade['value']:,.4f}, fee={trade['fee']:.8f} {trade.get('fee_asset', '?')}, "
            f"order_id={trade.get('order_id')}"
        )

    report.write(f"  After:  {fmt_balance(after_base, after_quote, after_price)}")

    ok = actual == expected_side
    icon = "✅" if ok else "❌"
    report.write(f"  {icon} expected={expected_side}, actual={actual}")
    report.record(name, ok, expected_side, actual)


def main() -> int:
    report = TestReport()
    report.write("=" * 70)
    report.write("Live Executor 통합 테스트 (Binance Testnet)")
    report.write("=" * 70)

    try:
        client = get_client(testnet=True)
    except RuntimeError as e:
        report.write(f"❌ Client 생성 실패: {e}")
        _save_results(report)
        return 1

    base, quote = split_symbol(SYMBOL)
    filters = get_symbol_filters(client, SYMBOL)
    report.write("")
    report.write("Symbol filters:")
    for k, v in filters.items():
        report.write(f"  {k}: {v}")

    init_base, init_quote = get_balances(client, base, quote)
    init_price = get_current_price(client, SYMBOL)
    init_equity = init_quote + init_base * init_price
    report.write("")
    report.write(f"Initial: {fmt_balance(init_base, init_quote, init_price)}")

    if init_quote < 100:
        report.write("⚠️ USDT 잔고가 너무 적음 ($100 미만). 테스트 중단.")
        _save_results(report)
        return 1

    # 테스트 시작 전 BTC가 있으면 먼저 정리해서 깨끗한 상태로 시작
    if init_base > float(filters["min_qty"]):
        report.write(f"\n[Pre-cleanup] 시작 전 BTC {init_base:.8f} 매도하여 0으로 리셋")
        try:
            rebalance_to_target(client, SYMBOL, 0.0, min_rebalance_frac=0)
            time.sleep(SETTLE_SLEEP)
        except Exception as e:
            report.write(f"  ⚠️ 사전 정리 실패: {e} (계속 진행)")

    # 시나리오 실행
    run_scenario(report, client, "Test 1: 0% → 25% (첫 매수)", 0.25, "buy")
    run_scenario(report, client, "Test 2: 25% → 50% (추가 매수)", 0.50, "buy")
    run_scenario(report, client, "Test 3: 50% → 30% (부분 매도)", 0.30, "sell")
    run_scenario(report, client, "Test 4: 30% → 0% (전량 매도)", 0.0, "sell")
    run_scenario(report, client, "Test 5: 0% → 0% (중복 요청, 스킵 예상)", 0.0, "skip")
    run_scenario(report, client, "Test 6: 0% → 0.001 (hysteresis 미만, 스킵 예상)",
                 0.001, "skip", min_rebalance_frac=0.01)

    # Cleanup
    report.write("")
    report.write("=" * 70)
    report.write("Cleanup — 남은 BTC 정리")
    report.write("=" * 70)
    final_base, final_quote = get_balances(client, base, quote)
    if final_base > float(filters["min_qty"]):
        try:
            rebalance_to_target(client, SYMBOL, 0.0, min_rebalance_frac=0)
            time.sleep(SETTLE_SLEEP)
        except Exception as e:
            report.write(f"  Cleanup 실패: {e}")

    final_base, final_quote = get_balances(client, base, quote)
    final_price = get_current_price(client, SYMBOL)
    final_equity = final_quote + final_base * final_price
    delta = final_equity - init_equity
    delta_pct = delta / init_equity * 100 if init_equity else 0
    report.write("")
    report.write(f"Final:    {fmt_balance(final_base, final_quote, final_price)}")
    report.write(f"Initial:  {fmt_balance(init_base, init_quote, init_price)}")
    report.write(f"Equity Δ: ${delta:+,.4f} ({delta_pct:+.4f}%) — 슬리피지 + 수수료 누적")

    # Summary
    passed = sum(1 for r in report.results if r["ok"])
    total = len(report.results)
    report.write("")
    report.write("=" * 70)
    report.write(f"SUMMARY: {passed}/{total} passed")
    report.write("=" * 70)
    for r in report.results:
        icon = "✅" if r["ok"] else "❌"
        report.write(f"  {icon} {r['name']}: expected={r['expected']}, actual={r['actual']}")

    _save_results(report)
    return 0 if passed == total else 1


def _save_results(report: TestReport):
    out_path = ROOT / "tasks" / "executor_test_results.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report.md(), encoding="utf-8")
    print(f"\n[Results saved] {out_path}")


if __name__ == "__main__":
    sys.exit(main())
