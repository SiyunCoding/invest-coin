"""멀티코인 현물 리밸런서.

- 잔고/가격은 매번 Binance 에서 조회 (source of truth)
- 매도 먼저 → USDT 확보 후 매수 (여러 종목 동시 리밸런스 시 잔고 부족 방지)
- LOT_SIZE 내림, MIN_NOTIONAL 미만 주문은 건너뜀 (소액 계좌 대응)
- 주문 하나가 거부돼도 나머지는 계속 (에러는 trade 로 기록)
"""
from __future__ import annotations

from datetime import datetime, timezone

from binance.client import Client
from binance.exceptions import BinanceAPIException

from .executor import _normalize_order, _round_down, get_symbol_filters, split_symbol


def get_free_balances(client: Client) -> dict[str, float]:
    account = client.get_account()
    return {b["asset"]: float(b["free"]) for b in account["balances"] if float(b["free"]) > 0}


def get_prices(client: Client) -> dict[str, float]:
    return {t["symbol"]: float(t["price"]) for t in client.get_all_tickers()}


def tradable_symbols(client: Client) -> set[str]:
    """이 계정(testnet/mainnet)에서 지금 주문 가능한 현물 심볼."""
    info = client.get_exchange_info()
    return {s["symbol"] for s in info["symbols"] if s.get("status") == "TRADING"}


def snapshot(balances: dict[str, float], prices: dict[str, float], symbols: set[str],
             quote: str = "USDT") -> tuple[float, dict[str, float], dict[str, float]]:
    """(총자산, {symbol: 보유수량}, {symbol: 비중}). 추적 심볼 외 자산은 무시."""
    cash = balances.get(quote, 0.0)
    qty, value = {}, {}
    for sym in symbols:
        base, _ = split_symbol(sym)
        q = balances.get(base, 0.0)
        if q > 0 and sym in prices:
            qty[sym] = q
            value[sym] = q * prices[sym]
    equity = cash + sum(value.values())
    weights = {s: v / equity for s, v in value.items()} if equity > 0 else {}
    return equity, qty, weights


def _error_trade(symbol: str, side: str, e: BinanceAPIException) -> dict:
    return {
        "time": datetime.now(timezone.utc).isoformat(), "side": "error", "symbol": symbol,
        "attempted": side, "error_code": e.code, "error_message": str(e.message),
    }


def rebalance_portfolio(
    client: Client,
    desired: dict[str, float],
    symbols: set[str],
    allow_buys: bool = True,
    min_trade_frac: float = 0.002,
    quote: str = "USDT",
) -> list[dict]:
    """desired {symbol: 총자산 대비 목표 비중} 에 맞춰 시장가 주문. 체결/에러 trade 목록 반환.

    min_trade_frac: 총자산 대비 이 비율 미만 변경은 생략 (먼지 주문 방지).
    allow_buys=False 면 매도만 (손실 한도 발동 시 위험 축소만 허용).
    """
    trades: list[dict] = []
    balances = get_free_balances(client)
    prices = get_prices(client)
    equity, qty, _ = snapshot(balances, prices, symbols | set(desired), quote)
    if equity <= 0:
        return trades

    deltas = {}
    for sym in symbols | set(desired):
        if sym not in prices:
            continue
        cur_val = qty.get(sym, 0.0) * prices[sym]
        deltas[sym] = desired.get(sym, 0.0) * equity - cur_val

    # 1) 매도
    for sym, delta in sorted(deltas.items(), key=lambda kv: kv[1]):
        if delta >= 0 or qty.get(sym, 0.0) <= 0:
            continue
        full_exit = desired.get(sym, 0.0) <= 0
        if not full_exit and -delta < equity * min_trade_frac:
            continue
        f = get_symbol_filters(client, sym)
        target_qty = qty[sym] if full_exit else min(-delta / prices[sym], qty[sym])
        sell_qty = _round_down(target_qty, f["lot_step"])
        if sell_qty < float(f["min_qty"]) or sell_qty * prices[sym] < float(f["min_notional"]):
            continue
        try:
            order = client.order_market_sell(symbol=sym, quantity=sell_qty)
            trades.append(_normalize_order(order, "sell", sym))
        except BinanceAPIException as e:
            trades.append(_error_trade(sym, "sell", e))

    if not allow_buys:
        return trades

    # 2) 매수 (매도 후 USDT 재조회)
    cash = get_free_balances(client).get(quote, 0.0)
    for sym, delta in sorted(deltas.items(), key=lambda kv: -kv[1]):
        if delta <= 0 or delta < equity * min_trade_frac:
            continue
        order_value = round(min(delta, cash * 0.999), 2)  # 수수료 여유분
        f = get_symbol_filters(client, sym)
        if order_value < float(f["min_notional"]) or order_value <= 0:
            continue
        try:
            order = client.order_market_buy(symbol=sym, quoteOrderQty=order_value)
            trade = _normalize_order(order, "buy", sym)
            trades.append(trade)
            cash -= float(trade.get("value", order_value))
        except BinanceAPIException as e:
            trades.append(_error_trade(sym, "buy", e))
    return trades
