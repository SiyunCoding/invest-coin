"""공용 테스트 도구: 가짜 Binance 현물 계정 + run_portfolio_tick 실행 환경 (네트워크 없음)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest


class FakeClient:
    """현물 계정 시뮬레이터. 시장가 주문은 현재가로 즉시 체결.

    실제 python-binance 처럼 수량/금액을 문자열로 받는다 (지수 표기면 거부).
    fee_rate: 체결 금액에서 USDT 로 떼는 수수료율. reject: 주문을 거부할 심볼 집합.
    """

    def __init__(self, balances, prices, fee_rate=0.0, reject=()):
        self.bal = dict(balances)
        self.prices = dict(prices)
        self.fee_rate = fee_rate
        self.reject = set(reject)
        self.orders = []

    def get_account(self):
        return {"balances": [{"asset": a, "free": str(v), "locked": "0"} for a, v in self.bal.items()]}

    def get_all_tickers(self):
        return [{"symbol": s, "price": str(p)} for s, p in self.prices.items()]

    def get_exchange_info(self):
        return {"symbols": [{
            "symbol": s, "status": "TRADING",
            "filters": [
                {"filterType": "LOT_SIZE", "stepSize": "0.00001", "minQty": "0.00001", "maxQty": "9000"},
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "NOTIONAL", "minNotional": "5"},
            ],
        } for s in self.prices]}

    @staticmethod
    def _parse(value: str) -> float:
        assert isinstance(value, str) and "e" not in value.lower(), f"bad numeric format {value!r}"
        return float(value)

    def _fill(self, symbol, side, qty, price):
        if symbol in self.reject:
            from binance.exceptions import BinanceAPIException

            class _Resp:
                status_code = 400
                text = '{"code": -2010, "msg": "rejected"}'

                def json(self):
                    return {"code": -2010, "msg": "rejected"}
            raise BinanceAPIException(_Resp(), 400, _Resp.text)
        base = symbol[:-4]
        value = qty * price
        fee = value * self.fee_rate
        if side == "buy":
            self.bal["USDT"] -= value
            self.bal[base] = self.bal.get(base, 0) + qty * (1 - self.fee_rate)
        else:
            self.bal[base] -= qty
            self.bal["USDT"] += value - fee
        self.orders.append((side, symbol, qty))
        return {"orderId": len(self.orders), "status": "FILLED", "transactTime": 0,
                "fills": [{"qty": str(qty), "price": str(price), "commission": str(fee), "commissionAsset": "USDT"}]}

    def order_market_buy(self, symbol, quoteOrderQty):
        p = self.prices[symbol]
        return self._fill(symbol, "buy", self._parse(quoteOrderQty) / p, p)

    def order_market_sell(self, symbol, quantity):
        return self._fill(symbol, "sell", self._parse(quantity), self.prices[symbol])


def make_daily(drift: float, rng, days: int = 900, end=None) -> pd.DataFrame:
    end = end or (datetime.now(timezone.utc) - timedelta(days=1)).date()
    idx = pd.date_range(end=pd.Timestamp(end, tz="UTC"), periods=days, freq="D")
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.02, len(idx))))
    return pd.DataFrame({"close": close, "quote_volume": 50e6}, index=idx)


@pytest.fixture
def tick_env(tmp_path, monkeypatch):
    """run_portfolio_tick 을 가짜 클라이언트 + 합성 일봉(어제까지)으로 돌리는 환경."""
    import src.live.portfolio_tick as pt

    rng = np.random.default_rng(42)
    data = {"BTCUSDT": make_daily(0.003, rng), "ETHUSDT": make_daily(0.003, rng),
            "XRPUSDT": make_daily(-0.003, rng)}
    client = FakeClient({"USDT": 10_000.0}, {s: float(d["close"].iloc[-1]) for s, d in data.items()})
    monkeypatch.setattr(pt, "get_client", lambda testnet=True: client)
    monkeypatch.setattr(pt, "_daily", lambda sym, cache_dir, lookback: data[sym])
    monkeypatch.setattr(pt, "_candidate_symbols", lambda pool: list(data))
    monkeypatch.setattr(pt, "send_telegram_message", lambda text: True)
    monkeypatch.setattr(pt, "HOME_HALT_FILE", tmp_path / "home" / ".invest-coin.halt")
    monkeypatch.setattr(pt.time, "sleep", lambda s: None)
    config = {"testnet": True, "min_equity_for_alts": 3000, "trend_rotation": {"alt_slots": 3},
              "safety": {"daily_loss_limit_pct": 0.05, "halt_file": ".halt"}}
    paths = {"state": tmp_path / "data" / "live_state.json", "dash": tmp_path / "docs" / "dash.html",
             "cache": tmp_path / "data", "root": tmp_path, "backup": tmp_path / "backups"}

    def run(**overrides):
        return pt.run_portfolio_tick(paths["state"], paths["dash"], {**config, **overrides},
                                     paths["cache"], root_dir=paths["root"], backup_dir=paths["backup"])

    return {"pt": pt, "client": client, "data": data, "paths": paths, "run": run}
