"""Trend Rotation 신호 / 유니버스 / 배분 단위 테스트.

실행: python -m pytest -q
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.portfolio import TrendRotationConfig, apply_band, is_eligible_symbol, select_universe, should_drop
from src.portfolio.allocator import weights_from_signals
from src.portfolio.signals import donchian_position, trend_fraction
from src.strategies.donchian_ensemble import DonchianEnsemble


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


def test_backtest_segment_suffix_is_eligible():
    """백테스트는 액면변경 후 시계열을 'LUNAUSDT#2' 로 분리 → 유니버스 후보에서 빠지면 안 됨."""
    daily = {"LUNAUSDT#2": _daily(400, 50e6)}
    assert select_universe(daily, top_n=5) == ["LUNAUSDT#2"]


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


def test_config_from_dict_ignores_unknown_and_casts_lookbacks():
    cfg = TrendRotationConfig.from_dict({"alt_slots": 5, "lookbacks": [10, 20], "unknown_key": 1})
    assert cfg.alt_slots == 5 and cfg.lookbacks == (10, 20)


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
