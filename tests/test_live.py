"""실매매 경로 테스트: 주문 실행기 + 일일 tick (가짜 거래소, 네트워크 없음)."""
from __future__ import annotations

import json
from decimal import Decimal

import pandas as pd
import pytest

from src.live.portfolio_executor import load_exchange, normalize_order, qty_string, rebalance_portfolio

from .conftest import FakeClient


def _state(env) -> dict:
    return json.loads(env["paths"]["state"].read_text(encoding="utf-8"))


def _write_state(env, state: dict) -> None:
    env["paths"]["state"].write_text(json.dumps(state), encoding="utf-8")


def _rules(client):
    return load_exchange(client)[1]


# ---------------- 실행기 ----------------
def test_qty_string_never_uses_exponent():
    assert qty_string(0.00007, Decimal("0.00001")) == "0.00007"
    assert qty_string(0.123456789, Decimal("0.001")) == "0.123"
    assert qty_string(12.0, Decimal("1")) == "12"
    assert qty_string(0.000004, Decimal("0.00001")) == "0"


def test_rebalance_sells_before_buys():
    c = FakeClient({"USDT": 100.0, "ETH": 1.0}, {"BTCUSDT": 100.0, "ETHUSDT": 900.0})
    # 총자산 1000: ETH 90% → 0, BTC 0 → 50%. USDT 100 뿐이라 매도가 먼저여야 매수 가능
    trades = rebalance_portfolio(c, {"BTCUSDT": 0.5, "ETHUSDT": 0.0}, {"BTCUSDT", "ETHUSDT"}, _rules(c))
    assert [t["side"] for t in trades] == ["sell", "buy"]
    assert c.bal["ETH"] == pytest.approx(0.0)
    assert c.bal["BTC"] * 100 == pytest.approx(500.0, rel=1e-3)


def test_rebalance_small_btc_sell_is_not_exponent_formatted():
    """BTC $80k 에서 $6 매도 = 0.000075 BTC → float 그대로면 '7.5e-05' 로 전송돼 거부됨."""
    c = FakeClient({"USDT": 2994.0, "BTC": 0.000075}, {"BTCUSDT": 80_000.0})
    trades = rebalance_portfolio(c, {"BTCUSDT": 0.0}, {"BTCUSDT"}, _rules(c))
    assert [t["side"] for t in trades] == ["sell"]


def test_rebalance_buy_block_allows_only_sells():
    c = FakeClient({"USDT": 500.0, "ETH": 0.5}, {"BTCUSDT": 100.0, "ETHUSDT": 1000.0})
    trades = rebalance_portfolio(c, {"BTCUSDT": 0.5, "ETHUSDT": 0.0}, {"BTCUSDT", "ETHUSDT"},
                                 _rules(c), allow_buys=False)
    assert all(t["side"] == "sell" for t in trades) and "BTC" not in c.bal


def test_rebalance_rejected_order_does_not_stop_others():
    c = FakeClient({"USDT": 1000.0}, {"BTCUSDT": 100.0, "ETHUSDT": 10.0}, reject={"BTCUSDT"})
    trades = rebalance_portfolio(c, {"BTCUSDT": 0.3, "ETHUSDT": 0.3}, {"BTCUSDT", "ETHUSDT"}, _rules(c))
    sides = {t["symbol"]: t["side"] for t in trades}
    assert sides == {"BTCUSDT": "error", "ETHUSDT": "buy"}


def test_normalize_order_aggregates_fills_and_handles_missing():
    order = {"orderId": 1, "status": "FILLED", "transactTime": 0, "fills": [
        {"qty": "1", "price": "10", "commission": "0.01", "commissionAsset": "USDT"},
        {"qty": "3", "price": "14", "commission": "0.02", "commissionAsset": "USDT"}]}
    t = normalize_order(order, "buy", "XUSDT")
    assert t["qty"] == 4 and t["price"] == pytest.approx(13.0) and t["fee"] == pytest.approx(0.03)
    t = normalize_order({"orderId": 2, "status": "NEW", "executedQty": "2", "cummulativeQuoteQty": "50"}, "buy", "XUSDT")
    assert t["value"] == 50 and t["price"] == 25 and t["status"] == "NEW"


# ---------------- tick ----------------
def test_tick_end_to_end_and_duplicate_bar(tick_env):
    res = tick_env["run"]()
    assert res["trades"], "상승 추세 종목이 있으니 첫 tick 에 매수가 있어야 함"
    assert res["weights"].get("BTCUSDT", 0) > res["weights"].get("XRPUSDT", 0)
    assert 0 < res["exposure"] <= 1.0
    state = _state(tick_env)
    assert state["strategy"] == "trend_rotation" and state["universe"]["symbols"]
    assert "Trend Rotation" in tick_env["paths"]["dash"].read_text(encoding="utf-8")

    n_orders = len(tick_env["client"].orders)
    res2 = tick_env["run"]()
    assert res2["duplicate_bar"] and len(tick_env["client"].orders) == n_orders


def test_tick_external_flow_excluded_from_nav(tick_env):
    tick_env["run"]()
    tick_env["client"].bal["USDT"] += 5_000.0   # testnet 잔고 리셋 같은 외부 유입
    res = tick_env["run"]()
    assert res["external_flow"] == pytest.approx(5_000.0, rel=1e-6)
    assert res["nav"] == pytest.approx(1.0, abs=1e-6)  # 가격 불변 → NAV 불변
    assert not res["buy_blocked"]


def test_tick_nav_includes_trading_costs(tick_env):
    tick_env["client"].fee_rate = 0.01
    res = tick_env["run"]()
    assert res["trades"] and res["nav"] < 1.0  # 수수료만큼 NAV 감소 (이전엔 1.0 그대로)


@pytest.mark.parametrize("where", ["repo", "home"])
def test_tick_halt_file_blocks_orders(tick_env, where):
    path = tick_env["paths"]["root"] / ".halt" if where == "repo" else tick_env["pt"].HOME_HALT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stop")
    res = tick_env["run"]()
    assert res["halted"] and not tick_env["client"].orders


def test_halt_keeps_prev_fracs_so_entry_retried_next_day(tick_env):
    """정지된 날 frac 변화를 '반영됨'으로 기록하면 다음 날 진입을 놓침 (밴드에 막힘)."""
    halt = tick_env["paths"]["root"] / ".halt"
    halt.write_text("stop")
    tick_env["run"]()
    assert _state(tick_env)["prev_fracs"] == {}
    halt.unlink()
    state = _state(tick_env)
    state["last_bar_time"] = None
    _write_state(tick_env, state)
    res = tick_env["run"]()
    assert any(t["side"] == "buy" for t in res["trades"])


def test_tick_loss_limit_blocks_buys_only(tick_env):
    tick_env["run"]()
    state = _state(tick_env)
    state["last_bar_time"] = None                 # 새 봉처럼
    state["history"][-1]["equity"] *= 1.2         # 직전 자산이 20% 더 높았던 것처럼
    _write_state(tick_env, state)
    before = len(tick_env["client"].orders)
    res = tick_env["run"]()
    assert res["buy_blocked"]
    assert all(side == "sell" for side, _, _ in tick_env["client"].orders[before:])


def test_small_account_btc_only_with_hysteresis(tick_env):
    tick_env["client"].bal["USDT"] = 500.0
    res = tick_env["run"]()
    assert not res["alts_enabled"] and set(res["weights"]) <= {"BTCUSDT"}

    pt = tick_env["pt"]
    assert pt._alts_enabled({"alts_enabled": True}, 2800, 3000)       # 켜져 있으면 2700 까지 유지
    assert not pt._alts_enabled({"alts_enabled": False}, 2800, 3000)  # 꺼져 있으면 3000 넘어야 켬


def test_untradable_universe_symbol_not_ordered(tick_env):
    del tick_env["client"].prices["XRPUSDT"]   # testnet 에 없는 페어
    res = tick_env["run"]()
    assert "XRPUSDT" in res["untradable"]
    assert all(sym != "XRPUSDT" for _, sym, _ in tick_env["client"].orders)


def test_stale_symbol_data_is_dropped(tick_env):
    """상장폐지/데이터 끊김: 마지막 봉이 기준 봉과 다르면 그 종목은 제외(보유분 청산)."""
    tick_env["data"]["ETHUSDT"] = tick_env["data"]["ETHUSDT"].iloc[:-5]
    res = tick_env["run"]()
    assert "ETHUSDT" in res["dropped"] and "ETHUSDT" not in res["targets"]


def test_held_symbol_sold_when_it_leaves_universe(tick_env):
    tick_env["run"]()
    assert tick_env["client"].bal.get("ETH", 0) > 0
    state = _state(tick_env)
    state["last_bar_time"] = None
    state["universe"] = {"symbols": ["BTCUSDT", "XRPUSDT"], "selected_at": pd.Timestamp.now(tz="UTC").isoformat()}
    _write_state(tick_env, state)
    tick_env["run"]()
    c = tick_env["client"]
    assert c.bal.get("ETH", 0) * c.prices["ETHUSDT"] < 1.0  # LOT_SIZE 내림 후 먼지만 남음
    assert "ETHUSDT" not in _state(tick_env)["holdings"]       # 먼지는 추적에서 빠짐


def test_missed_month_end_reselects_next_tick(tick_env):
    tick_env["run"]()
    state = _state(tick_env)
    state["last_bar_time"] = None
    state["universe"] = {"symbols": ["XRPUSDT"], "selected_at": "2020-01-31T00:00:00+00:00"}
    _write_state(tick_env, state)
    tick_env["run"]()
    assert _state(tick_env)["universe"]["selected_at"] != "2020-01-31T00:00:00+00:00"


def test_anomalous_targets_halt(tick_env, monkeypatch):
    pt = tick_env["pt"]
    monkeypatch.setattr(pt, "target_weights", lambda closes, uni, cfg: ({"BTCUSDT": float("nan")}, {"BTCUSDT": 1.0}))
    res = tick_env["run"]()
    assert res["halted"] and not tick_env["client"].orders


def test_state_saved_with_trades_when_post_trade_step_fails(tick_env, monkeypatch):
    """주문 후 잔고 재조회가 실패해도 체결 기록과 추적 종목은 저장 → 다음 tick 이 재동기화."""
    pt = tick_env["pt"]
    real = pt.get_free_balances
    calls = {"n": 0}

    def flaky(client):
        calls["n"] += 1
        if calls["n"] > 1 and tick_env["client"].orders:
            raise ConnectionError("network down")
        return real(client)
    monkeypatch.setattr(pt, "get_free_balances", flaky)
    with pytest.raises(ConnectionError):
        tick_env["run"]()
    state = _state(tick_env)
    assert state["resync"] and any(t["side"] == "buy" for t in state["trades"])
    assert "ETHUSDT" in state["holdings"]

    monkeypatch.setattr(pt, "get_free_balances", real)
    state["last_bar_time"] = None
    _write_state(tick_env, state)
    res = tick_env["run"]()
    assert res["external_flow"] == 0.0 and not _state(tick_env)["resync"]


def test_mode_change_archives_old_state(tick_env):
    tick_env["paths"]["state"].parent.mkdir(parents=True, exist_ok=True)
    _write_state(tick_env, {"strategy": "cycle_aware", "mode": "testnet"})
    tick_env["run"]()
    backups = list(tick_env["paths"]["backup"].glob("*.json"))
    assert len(backups) == 1 and "cycle_aware" in backups[0].name
    assert _state(tick_env)["strategy"] == "trend_rotation"


def test_live_tick_config_merge(tmp_path, monkeypatch):
    import scripts.live_tick as lt
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "live_trading.yaml").write_text(
        "testnet: false\nsafety:\n  daily_loss_limit_pct: 0.03\n", encoding="utf-8")
    monkeypatch.setattr(lt, "ROOT", tmp_path)
    cfg = lt._load_config()
    assert cfg["testnet"] is False
    assert cfg["safety"] == {"daily_loss_limit_pct": 0.03, "halt_file": ".halt"}  # 중첩 기본값 유지
    assert lt.DEFAULT_CONFIG["safety"]["daily_loss_limit_pct"] == 0.05            # 기본값 오염 없음


def test_alt_with_extra_bar_past_midnight_not_dropped(tick_env):
    """BTC 를 받은 뒤 UTC 자정이 지나 알트만 한 봉 더 받아도 '끊긴 데이터'로 오판해 청산하면 안 됨."""
    eth = tick_env["data"]["ETHUSDT"]
    extra = eth.iloc[[-1]].copy()
    extra.index = extra.index + pd.Timedelta(days=1)
    tick_env["data"]["ETHUSDT"] = pd.concat([eth, extra])
    res = tick_env["run"]()
    assert "ETHUSDT" not in res["dropped"] and "ETHUSDT" in res["universe"]


def test_universe_kept_when_most_candidates_fail(tick_env, monkeypatch):
    """rate limit 등으로 후보 대부분 실패 → 빈 유니버스로 한 달 고정되지 말고 기존 유지."""
    tick_env["run"]()
    before = _state(tick_env)["universe"]
    state = _state(tick_env)
    state["last_bar_time"] = None
    state["universe"]["selected_at"] = "2020-01-31T00:00:00+00:00"   # 재선정 필요한 상태
    _write_state(tick_env, state)
    pt, data = tick_env["pt"], tick_env["data"]

    def flaky(sym, cache_dir, lookback):
        if sym != "BTCUSDT":
            raise ConnectionError("429")
        return data[sym]
    monkeypatch.setattr(pt, "_daily", flaky)
    tick_env["run"]()
    after = _state(tick_env)["universe"]
    assert after["symbols"] == before["symbols"] and after["selected_at"] == "2020-01-31T00:00:00+00:00"


def test_market_max_qty_caps_sell():
    c = FakeClient({"USDT": 0.0, "ETH": 100.0}, {"ETHUSDT": 10.0})
    rules = _rules(c)
    from dataclasses import replace
    rules["ETHUSDT"] = replace(rules["ETHUSDT"], max_qty=Decimal("30"))
    rebalance_portfolio(c, {"ETHUSDT": 0.0}, {"ETHUSDT"}, rules)
    assert c.bal["ETH"] == pytest.approx(70.0)   # 30 만 팔고 나머지는 다음 tick


def test_mode_helper_matches_workflow_semantics():
    import scripts.live_tick as lt
    assert not lt.is_mainnet({}) and not lt.is_mainnet({"testnet": True})
    assert lt.is_mainnet({"testnet": False}) and lt.is_mainnet({"testnet": 0})
