"""Trend Rotation 단위/통합 테스트 (네트워크 없음 — 가짜 Binance 클라이언트).

실행: python -m pytest -q tests
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd
import pytest

from src.portfolio import TrendRotationConfig, apply_band, is_eligible_symbol, select_universe, should_drop
from src.portfolio.allocator import weights_from_signals
from src.strategies.donchian_ensemble import DonchianEnsemble, donchian_position, trend_fraction


def _series(values, start="2024-01-01"):
    idx = pd.date_range(start, periods=len(values), freq="D", tz="UTC")
    return pd.Series(values, index=idx, dtype=float)


# ---------------- 신호 ----------------
def test_donchian_enters_on_new_high_and_exits_below_mid():
    close = _series([10, 11, 12, 13, 14, 15, 9])  # 신고가 연속 → 마지막 날 중앙선 아래로 급락
    pos = donchian_position(close, 3)
    assert pos.iloc[2] == 1.0          # 12 = 3일 최고 → 진입
    assert pos.iloc[5] == 1.0
    assert pos.iloc[6] == 0.0          # 9 < 손절선(=이전 중앙값 래칫) → 청산


def test_holds_while_above_ratcheted_stop():
    close = _series([10, 11, 12, 12.5, 12.4, 12.6])
    pos = donchian_position(close, 3)
    assert pos.iloc[2:].eq(1.0).all()  # 손절선(래칫된 중앙값) 위에서 흔들림 → 유지
    # 래칫된 손절선(12.25) 아래로 내려오면 청산
    assert donchian_position(_series([10, 11, 12, 12.5, 12.4, 12.2]), 3).iloc[-1] == 0.0


def test_trend_fraction_bounds_and_no_lookahead():
    rng = np.random.default_rng(0)
    close = _series(100 * np.exp(np.cumsum(rng.normal(0, 0.03, 600))))
    full = trend_fraction(close)
    cut = trend_fraction(close.iloc[:400])
    assert full.between(0, 1).all()
    pd.testing.assert_series_equal(full.iloc[:400], cut)  # 미래 데이터가 과거 신호를 바꾸지 않음


def test_strategy_signal_capped():
    rng = np.random.default_rng(1)
    close = _series(100 * np.exp(np.cumsum(rng.normal(0.002, 0.01, 500))))
    sig = DonchianEnsemble().generate_signals(pd.DataFrame({"close": close}))
    assert sig.between(0, 1).all() and sig.iloc[-1] > 0


# ---------------- 유니버스 ----------------
@pytest.mark.parametrize("sym,ok", [
    ("BTCUSDT", True), ("ETHUSDT", True), ("USDCUSDT", False), ("BTCUPUSDT", False),
    ("ETHBULLUSDT", False), ("BULLUSDT", False), ("WBTCUSDT", False), ("EURUSDT", False), ("BTCBUSD", False),
])
def test_eligible_symbol(sym, ok):
    assert is_eligible_symbol(sym) is ok


def _daily(days, vol, move=0.02):
    idx = pd.date_range(end="2026-10-28", periods=days, freq="D", tz="UTC")
    close = 100 * np.cumprod(1 + np.where(np.arange(days) % 2, move, -move))
    return pd.DataFrame({"close": close, "quote_volume": vol}, index=idx)


def test_select_universe_filters_age_and_volume():
    daily = {
        "AAAUSDT": _daily(400, 50e6), "BBBUSDT": _daily(400, 10e6),
        "YOUNGUSDT": _daily(200, 900e6),   # 상장 365일 미만
        "THINUSDT": _daily(400, 1e6),      # 거래대금 미달
        "USDCUSDT": _daily(400, 999e6),    # 스테이블
    }
    assert select_universe(daily, top_n=5) == ["AAAUSDT", "BBBUSDT"]
    assert select_universe(daily, top_n=1) == ["AAAUSDT"]


def test_should_drop_illiquid_or_flat():
    assert should_drop(_daily(60, 0.5e6))
    assert should_drop(_daily(60, 50e6, move=0.001))
    assert not should_drop(_daily(60, 50e6))


# ---------------- 배분 / 밴드 ----------------
def test_weights_from_signals_sleeves_and_cap():
    cfg = TrendRotationConfig()
    w, f = weights_from_signals((1.0, 1.0), {"BTCUSDT": (1.0, 1.0), "ETHUSDT": (0.5, 0.8)}, cfg)
    assert w["BTCUSDT"] == pytest.approx(0.5 + 0.05)
    assert w["ETHUSDT"] == pytest.approx(0.05 * 0.5 * 0.8)
    assert sum(w.values()) <= 1.0


def test_band_ignores_small_vol_drift_but_follows_signal_change():
    cfg = TrendRotationConfig()
    uni = ["ETHUSDT"]
    # 신호 동일, 변동성 때문에 목표가 조금 변함 → 유지
    out = apply_band({"ETHUSDT": 0.040}, {"ETHUSDT": 0.045}, {"ETHUSDT": 0.5}, {"ETHUSDT": 0.5}, uni, cfg)
    assert out["ETHUSDT"] == 0.045
    # 신호 변화 → 즉시 목표
    out = apply_band({"ETHUSDT": 0.040}, {"ETHUSDT": 0.045}, {"ETHUSDT": 0.6}, {"ETHUSDT": 0.5}, uni, cfg)
    assert out["ETHUSDT"] == 0.040
    # 유니버스 탈락한 보유 종목 → 0
    out = apply_band({}, {"XRPUSDT": 0.03}, {}, {"XRPUSDT": 0.4}, uni, cfg)
    assert out["XRPUSDT"] == 0.0


# ---------------- 실행기 + tick 통합 ----------------
class FakeClient:
    """현물 계정 시뮬레이터. 시장가 주문은 현재가로 즉시 체결, 수수료 0."""

    def __init__(self, balances, prices):
        self.bal = dict(balances)
        self.prices = dict(prices)
        self.orders = []

    def get_account(self):
        return {"balances": [{"asset": a, "free": str(v), "locked": "0"} for a, v in self.bal.items()]}

    def get_all_tickers(self):
        return [{"symbol": s, "price": str(p)} for s, p in self.prices.items()]

    def get_exchange_info(self):
        return {"symbols": [{"symbol": s, "status": "TRADING"} for s in self.prices]}

    def get_symbol_info(self, symbol):
        return {"filters": [
            {"filterType": "LOT_SIZE", "stepSize": "0.00001", "minQty": "0.00001", "maxQty": "9000"},
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
            {"filterType": "NOTIONAL", "minNotional": "5"},
        ]}

    def _fill(self, symbol, side, qty, price):
        base = symbol[:-4]
        if side == "buy":
            self.bal["USDT"] -= qty * price
            self.bal[base] = self.bal.get(base, 0) + qty
        else:
            self.bal[base] -= qty
            self.bal["USDT"] += qty * price
        self.orders.append((side, symbol, qty))
        return {"orderId": len(self.orders), "status": "FILLED", "transactTime": 0,
                "fills": [{"qty": str(qty), "price": str(price), "commission": "0", "commissionAsset": "USDT"}]}

    def order_market_buy(self, symbol, quoteOrderQty):
        p = self.prices[symbol]
        return self._fill(symbol, "buy", quoteOrderQty / p, p)

    def order_market_sell(self, symbol, quantity):
        return self._fill(symbol, "sell", quantity, self.prices[symbol])


def test_rebalance_sells_before_buys_and_skips_dust():
    from src.live.portfolio_executor import rebalance_portfolio
    c = FakeClient({"USDT": 100.0, "ETH": 1.0}, {"BTCUSDT": 100.0, "ETHUSDT": 900.0})
    # 총자산 1000: ETH 90% → 0, BTC 0 → 50%. USDT 100 뿐이라 매도가 먼저여야 매수 가능
    trades = rebalance_portfolio(c, {"BTCUSDT": 0.5, "ETHUSDT": 0.0}, {"BTCUSDT", "ETHUSDT"})
    assert [t["side"] for t in trades] == ["sell", "buy"]
    assert c.bal["ETH"] == pytest.approx(0.0)
    assert c.bal["BTC"] * 100 == pytest.approx(500.0, rel=1e-3)


def test_rebalance_buy_block_allows_only_sells():
    from src.live.portfolio_executor import rebalance_portfolio
    c = FakeClient({"USDT": 500.0, "ETH": 0.5}, {"BTCUSDT": 100.0, "ETHUSDT": 1000.0})
    trades = rebalance_portfolio(c, {"BTCUSDT": 0.5, "ETHUSDT": 0.0}, {"BTCUSDT", "ETHUSDT"}, allow_buys=False)
    assert all(t["side"] == "sell" for t in trades) and "BTC" not in c.bal


@pytest.fixture
def tick_env(tmp_path, monkeypatch):
    """run_portfolio_tick 을 가짜 클라이언트 + 합성 일봉으로 돌리는 환경."""
    import src.live.portfolio_tick as pt

    rng = np.random.default_rng(42)
    idx = pd.date_range(end="2026-10-27", periods=900, freq="D", tz="UTC")

    def trending(drift):
        close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.02, len(idx))))
        return pd.DataFrame({"close": close, "quote_volume": 50e6}, index=idx)

    data = {"BTCUSDT": trending(0.003), "ETHUSDT": trending(0.003), "XRPUSDT": trending(-0.003)}
    client = FakeClient({"USDT": 10_000.0},
                        {s: float(d["close"].iloc[-1]) for s, d in data.items()})
    monkeypatch.setattr(pt, "get_client", lambda testnet=True: client)
    monkeypatch.setattr(pt, "_daily", lambda sym, cache_dir, lookback: data[sym])
    monkeypatch.setattr(pt, "_candidate_symbols", lambda pool: list(data))
    monkeypatch.setattr(pt, "send_telegram_message", lambda text: True)
    monkeypatch.setattr(pt, "HOME_HALT_FILE", tmp_path / "home" / ".invest-coin.halt")
    config = {"testnet": True, "min_equity_for_alts": 3000, "trend_rotation": {"alt_slots": 3},
              "safety": {"daily_loss_limit_pct": 0.05, "halt_file": ".halt"}}
    paths = (tmp_path / "data" / "live_state.json", tmp_path / "docs" / "dash.html", tmp_path / "data")
    return pt, client, config, paths


def test_tick_end_to_end(tick_env):
    pt, client, config, (state_path, dash_path, cache_dir) = tick_env
    res = pt.run_portfolio_tick(state_path, dash_path, config, cache_dir)
    assert res["trades"], "상승 추세 종목이 있으니 첫 tick 에 매수가 있어야 함"
    assert res["weights"].get("BTCUSDT", 0) > res["weights"].get("XRPUSDT", 0)
    assert 0 < res["exposure"] <= 1.0
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["strategy"] == "trend_rotation" and state["universe"]["symbols"]
    assert dash_path.exists() and "Trend Rotation" in dash_path.read_text(encoding="utf-8")

    # 같은 봉 재실행 → 주문 없음
    n_orders = len(client.orders)
    res2 = pt.run_portfolio_tick(state_path, dash_path, config, cache_dir)
    assert res2["duplicate_bar"] and len(client.orders) == n_orders


def test_tick_detects_external_flow_and_keeps_nav(tick_env):
    pt, client, config, (state_path, dash_path, cache_dir) = tick_env
    pt.run_portfolio_tick(state_path, dash_path, config, cache_dir)
    client.bal["USDT"] += 5_000.0   # testnet 잔고 리셋 같은 외부 유입
    res = pt.run_portfolio_tick(state_path, dash_path, config, cache_dir)
    assert res["external_flow"] == pytest.approx(5_000.0, rel=1e-6)
    assert res["nav"] == pytest.approx(1.0, abs=1e-6)  # 가격 불변 → NAV 불변
    assert not res["buy_blocked"]


def test_tick_halt_file_blocks_orders(tick_env):
    pt, client, config, (state_path, dash_path, cache_dir) = tick_env
    (cache_dir.parent / ".halt").parent.mkdir(parents=True, exist_ok=True)
    (cache_dir.parent / ".halt").write_text("stop")
    res = pt.run_portfolio_tick(state_path, dash_path, config, cache_dir)
    assert res["halted"] and not client.orders


def test_tick_home_halt_file_blocks_orders(tick_env):
    """러너 작업 폴더는 매번 git clean 되므로 서버 홈의 halt 파일도 인식해야 함."""
    pt, client, config, (state_path, dash_path, cache_dir) = tick_env
    pt.HOME_HALT_FILE.parent.mkdir(parents=True, exist_ok=True)
    pt.HOME_HALT_FILE.write_text("stop")
    res = pt.run_portfolio_tick(state_path, dash_path, config, cache_dir)
    assert res["halted"] and not client.orders


def test_tick_loss_limit_blocks_buys_only(tick_env):
    pt, client, config, (state_path, dash_path, cache_dir) = tick_env
    pt.run_portfolio_tick(state_path, dash_path, config, cache_dir)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["last_bar_time"] = None                          # 새 봉처럼
    state["history"][-1]["equity"] *= 1.2                  # 직전 자산이 20% 더 높았던 것처럼
    state_path.write_text(json.dumps(state), encoding="utf-8")
    before = len(client.orders)
    res = pt.run_portfolio_tick(state_path, dash_path, config, cache_dir)
    assert res["buy_blocked"]
    assert all(side == "sell" for side, _, _ in client.orders[before:])


def test_small_account_falls_back_to_btc_only(tick_env):
    pt, client, config, (state_path, dash_path, cache_dir) = tick_env
    client.bal["USDT"] = 500.0
    res = pt.run_portfolio_tick(state_path, dash_path, config, cache_dir)
    assert not res["alts_enabled"]
    assert set(res["weights"]) <= {"BTCUSDT"}
