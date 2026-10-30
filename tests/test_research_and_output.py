"""백테스트 엔진/지표 회귀 테스트 + 알림/대시보드 출력 안전성."""
from __future__ import annotations

import pandas as pd
import pytest

from src.backtest.engine import run_backtest
from src.backtest.metrics import cagr
from src.common.dashboard import render_dashboard
from src.notifier import format_portfolio_notification
from src.strategies.base import Strategy


class _Fixed(Strategy):
    def __init__(self, values):
        self.values = values

    def generate_signals(self, ohlcv):
        return pd.Series(self.values, index=ohlcv.index, dtype=float)


def _ohlcv(closes):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D", tz="UTC")
    return pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes}, index=idx)


def test_extract_trades_uses_actual_entry_and_exit_bars():
    """신호 1,1,1,0 → 첫 봉 종가 100 에 진입, 셋째 봉 종가 133.1 에 청산 (+33.1%)."""
    df = _ohlcv([100, 110, 121, 133.1, 100, 100])
    res = run_backtest(df, _Fixed([1, 1, 1, 0, 0, 0]), fee_rate=0.0, slippage_rate=0.0)
    t = res.trades.iloc[0]
    assert t["entry_price"] == 100 and t["exit_price"] == pytest.approx(133.1)
    assert t["gross_return"] == pytest.approx(0.331) and t["net_return"] == pytest.approx(0.331)


def test_optimizer_max_drawdown_picks_shallowest():
    from src.backtest import grid_search
    import numpy as np
    rng = np.random.default_rng(0)
    df = _ohlcv(list(100 * np.exp(np.cumsum(rng.normal(0.001, 0.03, 900)))))
    opt = grid_search(df, "donchian_ensemble", {"target_vol": [0.2, 1.0]}, metric="max_drawdown")
    assert opt.table["max_drawdown"].iloc[0] == opt.table["max_drawdown"].max()


def test_cagr_nan_for_very_short_series():
    idx = pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC")
    assert pd.isna(cagr(pd.Series([100.0, 101.0], index=idx)))


def test_dashboard_escapes_script_breakout(tmp_path):
    state = {"mode": "testnet", "history": [{"time": "2026-10-29T00:00:00+00:00", "equity": 100.0,
                                             "weights": {"</script><script>alert(1)//USDT": 0.5}, "btc_price": 1.0}],
             "holdings": {}, "trades": [{"side": "error", "symbol": "<b>X</b>", "time": "2026-10-29T00:00:00+00:00"}]}
    out = tmp_path / "d.html"
    render_dashboard(state, out)
    html = out.read_text(encoding="utf-8")
    assert "</script><script>alert(1)" not in html and "<b>X</b>" not in html


def test_notification_handles_errors_and_empty_state():
    msg = format_portfolio_notification({
        "mode": "testnet", "trades": [{"side": "error", "symbol": "BTCUSDT", "attempted": "buy",
                                       "error_code": -2010, "error_message": "rejected"}],
        "equity": 0, "exposure": 0, "nav": 1.0, "btc_return": 0.0, "weights": {},
        "halted": True, "reasons": ["halt 파일 존재"], "external_flow": 0, "untradable": [],
    })
    assert "매매 정지" in msg and "실패" in msg


def test_telegram_network_error_hides_token(monkeypatch, capsys):
    import src.notifier.telegram as tg
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:SECRET")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")

    def boom(*a, **k):
        raise ConnectionError("Max retries exceeded with url: /bot123:SECRET/sendMessage")
    monkeypatch.setattr(tg.requests, "post", boom)
    assert tg.send_telegram_message("hi") is False
    assert "SECRET" not in capsys.readouterr().out
