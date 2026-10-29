"""Binance 현물 주문 공용 헬퍼 (portfolio_executor 가 사용).

  - 심볼 분리, 거래소 규칙(LOT_SIZE / MIN_NOTIONAL / PRICE_FILTER) 조회
  - LOT_SIZE step 내림
  - 체결 결과 정규화 (trade dict 형식)

주의:
  - Source of truth = Binance 잔고. 우리 state.json은 히스토리만 저장.
  - 부분 체결 시 fills 합산해서 평균가/총 수수료 계산.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal

from binance.client import Client


def split_symbol(symbol: str) -> tuple[str, str]:
    """BTCUSDT → ('BTC', 'USDT')."""
    for quote in ("USDT", "USDC", "BUSD", "USD", "BTC", "ETH"):
        if symbol.endswith(quote):
            return symbol[:-len(quote)], quote
    raise ValueError(f"Cannot split symbol: {symbol}")


def get_symbol_filters(client: Client, symbol: str) -> dict:
    """Binance 거래소 규칙. exchangeInfo에서 한 번 받아서 반환."""
    info = client.get_symbol_info(symbol)
    if info is None:
        raise ValueError(f"Symbol not found on Binance: {symbol}")
    filters = {f["filterType"]: f for f in info["filters"]}
    lot = filters["LOT_SIZE"]
    price = filters["PRICE_FILTER"]
    # MIN_NOTIONAL과 NOTIONAL 둘 다 가능 (Binance 마이그레이션 중)
    notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL", {})
    min_notional = notional.get("minNotional") or notional.get("notional") or "0"
    return {
        "lot_step": Decimal(lot["stepSize"]),
        "min_qty": Decimal(lot["minQty"]),
        "max_qty": Decimal(lot["maxQty"]),
        "price_step": Decimal(price["tickSize"]),
        "min_notional": Decimal(min_notional),
    }


def _round_down(value: float, step: Decimal) -> float:
    """step의 배수로 내림. 거래소 LOT_SIZE 규칙용."""
    d = Decimal(str(value))
    return float((d / step).to_integral_value(rounding=ROUND_DOWN) * step)


def get_balances(client: Client, base: str, quote: str) -> tuple[float, float]:
    """(base_free, quote_free) 반환. 'locked'(미체결 주문)은 제외."""
    account = client.get_account()
    balances = {b["asset"]: float(b["free"]) for b in account["balances"]}
    return balances.get(base, 0.0), balances.get(quote, 0.0)


def get_current_price(client: Client, symbol: str) -> float:
    ticker = client.get_symbol_ticker(symbol=symbol)
    return float(ticker["price"])


def _normalize_order(order: dict, side: str, symbol: str) -> dict:
    """Binance 주문 응답 → 우리 표준 trade dict.

    부분 체결이 여러 fills로 쪼개진 경우 모두 합산해 평균가/총 수수료 산출.
    """
    fills = order.get("fills", [])
    if not fills:
        # 주문은 들어갔는데 fills 없음 (FILLED 상태 아님). 보수적으로 표시.
        return {
            "time": datetime.now(timezone.utc).isoformat(),
            "side": side,
            "qty": 0.0,
            "price": 0.0,
            "value": 0.0,
            "fee": 0.0,
            "order_id": order.get("orderId"),
            "status": order.get("status", "UNKNOWN"),
            "symbol": symbol,
        }
    total_qty = sum(float(f["qty"]) for f in fills)
    total_value = sum(float(f["price"]) * float(f["qty"]) for f in fills)
    total_fee = sum(float(f["commission"]) for f in fills)
    fee_asset = fills[0].get("commissionAsset", "")
    avg_price = total_value / total_qty if total_qty > 0 else 0.0
    return {
        "time": datetime.fromtimestamp(
            order.get("transactTime", 0) / 1000, tz=timezone.utc
        ).isoformat(),
        "side": side,
        "qty": total_qty,
        "price": avg_price,
        "value": total_value,
        "fee": total_fee,
        "fee_asset": fee_asset,
        "order_id": order.get("orderId"),
        "status": order.get("status"),
        "symbol": symbol,
    }

