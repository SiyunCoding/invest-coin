"""멀티코인 현물 리밸런서 + Binance 주문 헬퍼.

- 잔고/가격은 매번 Binance 에서 조회 (source of truth)
- 거래소 규칙(LOT_SIZE / MARKET_LOT_SIZE / NOTIONAL)은 exchangeInfo 한 번으로 미리 로드
- 매도 먼저 → USDT 확보 후 매수 (여러 종목 동시 리밸런스 시 잔고 부족 방지)
- 수량/금액은 고정소수 문자열로 전송 (float → '7e-05' 같은 지수 표기는 Binance 가 거부)
- 주문 하나가 실패해도 나머지 종목은 계속 (에러는 trade 로 기록, 예외 종류 무관)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal

from binance.client import Client

from ..utils.symbols import split_symbol


@dataclass(frozen=True)
class SymbolRules:
    step: Decimal          # 시장가 수량 단위 (MARKET_LOT_SIZE 가 있으면 그것, 없으면 LOT_SIZE)
    min_qty: Decimal
    min_notional: Decimal


def _decimal(x) -> Decimal:
    return Decimal(str(x))


def load_exchange(client: Client) -> tuple[set[str], dict[str, SymbolRules]]:
    """(지금 거래 가능한 심볼, 심볼별 주문 규칙). exchangeInfo 1회 호출."""
    info = client.get_exchange_info()
    tradable, rules = set(), {}
    for s in info["symbols"]:
        if s.get("status") != "TRADING":
            continue
        tradable.add(s["symbol"])
        f = {x["filterType"]: x for x in s.get("filters", [])}
        lot = f.get("LOT_SIZE", {})
        mkt = f.get("MARKET_LOT_SIZE", {})
        step = _decimal(lot.get("stepSize", "0"))
        if _decimal(mkt.get("stepSize", "0")) > step:
            step = _decimal(mkt["stepSize"])
        notional = f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}
        rules[s["symbol"]] = SymbolRules(
            step=step if step > 0 else Decimal("0.00000001"),
            min_qty=_decimal(lot.get("minQty", "0")),
            min_notional=_decimal(notional.get("minNotional") or notional.get("notional") or "0"),
        )
    return tradable, rules


def qty_string(value: float, step: Decimal) -> str:
    """step 배수로 내림한 수량을 고정소수 문자열로 ('0.00007', 지수 표기 없음)."""
    q = (_decimal(value) / step).to_integral_value(rounding=ROUND_DOWN) * step
    return format(q.normalize(), "f") if q > 0 else "0"


def get_free_balances(client: Client) -> dict[str, float]:
    account = client.get_account()
    return {b["asset"]: float(b["free"]) for b in account["balances"] if float(b["free"]) > 0}


def get_prices(client: Client) -> dict[str, float]:
    return {t["symbol"]: float(t["price"]) for t in client.get_all_tickers()}


def snapshot(balances: dict[str, float], prices: dict[str, float], symbols: set[str],
             quote: str = "USDT") -> tuple[float, dict[str, float], dict[str, float]]:
    """(총자산, {symbol: 보유수량}, {symbol: 비중}). 추적 심볼 외 자산은 무시."""
    cash = balances.get(quote, 0.0)
    qty, value = {}, {}
    for sym in symbols:
        if sym not in prices:
            continue
        q = balances.get(split_symbol(sym)[0], 0.0)
        if q > 0:
            qty[sym] = q
            value[sym] = q * prices[sym]
    equity = cash + sum(value.values())
    weights = {s: v / equity for s, v in value.items()} if equity > 0 else {}
    return equity, qty, weights


def normalize_order(order: dict, side: str, symbol: str) -> dict:
    """Binance 주문 응답 → trade dict. fills 를 합산해 평균가/총 수수료 산출."""
    fills = order.get("fills") or []
    total_qty = sum(float(f["qty"]) for f in fills) or float(order.get("executedQty", 0) or 0)
    total_value = (sum(float(f["price"]) * float(f["qty"]) for f in fills)
                   or float(order.get("cummulativeQuoteQty", 0) or 0))
    ts = order.get("transactTime")
    return {
        "time": (datetime.fromtimestamp(ts / 1000, tz=timezone.utc) if ts else datetime.now(timezone.utc)).isoformat(),
        "side": side,
        "symbol": symbol,
        "qty": total_qty,
        "price": total_value / total_qty if total_qty > 0 else 0.0,
        "value": total_value,
        "fee": sum(float(f["commission"]) for f in fills),
        "fee_asset": fills[0].get("commissionAsset", "") if fills else "",
        "order_id": order.get("orderId"),
        "status": order.get("status", "UNKNOWN"),
    }


def _error_trade(symbol: str, side: str, e: Exception) -> dict:
    return {
        "time": datetime.now(timezone.utc).isoformat(), "side": "error", "symbol": symbol,
        "attempted": side, "error_code": getattr(e, "code", type(e).__name__),
        "error_message": str(getattr(e, "message", e))[:300],
    }


def rebalance_portfolio(
    client: Client,
    desired: dict[str, float],
    symbols: set[str],
    rules: dict[str, SymbolRules],
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
    universe = symbols | set(desired)
    equity, qty, _ = snapshot(balances, prices, universe, quote)
    if equity <= 0:
        return trades

    deltas = {s: desired.get(s, 0.0) * equity - qty.get(s, 0.0) * prices[s]
              for s in universe if s in prices and s in rules}

    # 1) 매도 (줄일 금액 큰 순)
    for sym, delta in sorted(deltas.items(), key=lambda kv: kv[1]):
        if delta >= 0 or qty.get(sym, 0.0) <= 0:
            continue
        full_exit = desired.get(sym, 0.0) <= 0
        if not full_exit and -delta < equity * min_trade_frac:
            continue
        r = rules[sym]
        target = qty[sym] if full_exit else min(-delta / prices[sym], qty[sym])
        q = qty_string(target, r.step)
        if _decimal(q) < max(r.min_qty, r.step) or _decimal(q) * _decimal(prices[sym]) < r.min_notional:
            continue
        try:
            trades.append(normalize_order(client.order_market_sell(symbol=sym, quantity=q), "sell", sym))
        except Exception as e:  # 한 종목 실패가 나머지를 막지 않게
            trades.append(_error_trade(sym, "sell", e))

    if not allow_buys:
        return trades

    # 2) 매수 (늘릴 금액 큰 순, 매 주문 전 USDT 재조회)
    for sym, delta in sorted(deltas.items(), key=lambda kv: -kv[1]):
        if delta <= 0 or delta < equity * min_trade_frac:
            continue
        try:
            cash = get_free_balances(client).get(quote, 0.0)
            amount = min(delta, cash * 0.999)  # 수수료 여유분
            if _decimal(f"{amount:.2f}") < max(rules[sym].min_notional, Decimal("0.01")):
                continue
            order = client.order_market_buy(symbol=sym, quoteOrderQty=f"{amount:.2f}")
            trades.append(normalize_order(order, "buy", sym))
        except Exception as e:
            trades.append(_error_trade(sym, "buy", e))
    return trades
