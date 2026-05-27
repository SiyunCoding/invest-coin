"""Binance Futures 실 매매 실행기 (50x scalping용).

핵심 책임:
  - 레버리지 / 마진 모드 설정 (1회)
  - SHORT 시장가 진입 (RSI > 70 신호 시)
  - TAKE_PROFIT_MARKET 자동 청산 주문 (Binance가 가격 도달 시 처리)
  - 현 포지션 조회 (source of truth = Binance)
  - LOT_SIZE / PRICE_FILTER 자동 적용

설계 원칙:
  - 익절은 서버 사이드 (TAKE_PROFIT_MARKET + closePosition=True)
  - 손절은 안 함 (50x에서 −2% 가격 = Binance 강제 청산)
  - 마진은 고정 USDT 금액 (예: 15 USDT)
"""
from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Optional

from binance.client import Client
from binance.exceptions import BinanceAPIException


TAKER_FEE_RATE = 0.0004  # Binance Futures taker 0.04%


def get_symbol_filters(client: Client, symbol: str) -> dict:
    """Futures exchange info에서 LOT_SIZE / PRICE_FILTER 추출."""
    info = client.futures_exchange_info()
    for s in info["symbols"]:
        if s["symbol"] == symbol:
            filters = {f["filterType"]: f for f in s["filters"]}
            return {
                "lot_step": Decimal(filters["LOT_SIZE"]["stepSize"]),
                "min_qty": Decimal(filters["LOT_SIZE"]["minQty"]),
                "price_step": Decimal(filters["PRICE_FILTER"]["tickSize"]),
                "min_notional": Decimal(filters.get("MIN_NOTIONAL", {}).get("notional", "0")),
            }
    raise ValueError(f"Futures symbol not found: {symbol}")


def _round_step(value: float, step: Decimal, rounding=ROUND_DOWN) -> float:
    d = Decimal(str(value))
    return float((d / step).to_integral_value(rounding=rounding) * step)


def ensure_leverage_and_margin(
    client: Client, symbol: str, leverage: int, margin_type: str = "CROSSED"
) -> None:
    """진입 전 1회 호출. 이미 설정되어 있으면 무시.

    margin_type: "CROSSED" (cross) or "ISOLATED".
    """
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
    except BinanceAPIException as e:
        # 이미 같은 레버리지면 에러 — 무시
        if e.code not in (-4046, -4047):
            raise
    try:
        client.futures_change_margin_type(symbol=symbol, marginType=margin_type)
    except BinanceAPIException as e:
        # "No need to change margin type" = -4046
        if e.code != -4046:
            raise


def get_mark_price(client: Client, symbol: str) -> float:
    return float(client.futures_mark_price(symbol=symbol)["markPrice"])


def get_position_amt(client: Client, symbol: str) -> float:
    """현재 포지션 수량. SHORT면 음수, LONG이면 양수, 없으면 0."""
    positions = client.futures_position_information(symbol=symbol)
    for p in positions:
        if p["symbol"] == symbol:
            return float(p["positionAmt"])
    return 0.0


def get_available_balance(client: Client, asset: str = "USDT") -> float:
    """선물 지갑의 사용 가능 USDT."""
    balances = client.futures_account_balance()
    for b in balances:
        if b["asset"] == asset:
            return float(b["availableBalance"])
    return 0.0


def open_short_with_tp(
    client: Client,
    symbol: str,
    margin_usdt: float,
    leverage: int,
    tp_profit_pct: float,
    cushion_usdt: float = 2.0,
) -> dict:
    """50x SHORT 진입 + TP 자동 청산 주문 한 번에.

    Args:
        margin_usdt: 마진 금액 (예: 15)
        leverage: 레버리지 배수 (예: 50)
        tp_profit_pct: TP 익절 기준 (마진 대비 비율, 예: 0.30 = 마진 30%)
        cushion_usdt: 추가 안전 마진 ($) — 수수료 + 슬리피지 위에 얼마 더 벌지

    Returns: {entry, tp, qty, entry_price, tp_stop_price}.
    Raises: BinanceAPIException 그대로 propagate.
    """
    notional = margin_usdt * leverage
    mark_price = get_mark_price(client, symbol)
    filters = get_symbol_filters(client, symbol)

    qty_target = notional / mark_price
    qty = _round_step(qty_target, filters["lot_step"], ROUND_DOWN)
    if qty < float(filters["min_qty"]):
        raise ValueError(
            f"qty {qty} < min_qty {filters['min_qty']} "
            f"(margin {margin_usdt} × lev {leverage} 너무 작음)"
        )

    # 1) SHORT 시장가 진입
    entry = client.futures_create_order(
        symbol=symbol,
        side="SELL",
        type="MARKET",
        quantity=qty,
    )
    # entry response에 avgPrice 안 들어있을 수 있음 — position에서 다시 조회
    # 또는 cumQuote / executedQty로 계산
    executed_qty = float(entry.get("executedQty", qty))
    cum_quote = float(entry.get("cumQuote", qty * mark_price))
    entry_price = cum_quote / executed_qty if executed_qty > 0 else mark_price

    # 2) TP stop price 계산
    # SHORT profit = (entry - exit) × qty
    # 목표: net P&L (after fees) = margin × tp_profit_pct + cushion
    # fees = notional × taker_fee × 2 (진입 + 청산)
    fees = notional * TAKER_FEE_RATE * 2
    target_gross_profit = margin_usdt * tp_profit_pct + cushion_usdt + fees
    price_drop_needed = target_gross_profit / qty
    tp_stop_price_raw = entry_price - price_drop_needed
    tp_stop_price = _round_step(tp_stop_price_raw, filters["price_step"], ROUND_HALF_UP)

    # 3) TAKE_PROFIT_MARKET 주문 (서버에서 가격 도달 시 자동 청산)
    tp = client.futures_create_order(
        symbol=symbol,
        side="BUY",  # SHORT 닫으려면 반대로 BUY
        type="TAKE_PROFIT_MARKET",
        stopPrice=tp_stop_price,
        closePosition=True,
        timeInForce="GTE_GTC",  # Good Till Executed/Cancelled
        workingType="MARK_PRICE",  # mark price 기준 (가장 안정적)
    )

    return {
        "entry": entry,
        "tp": tp,
        "qty": qty,
        "entry_price": entry_price,
        "tp_stop_price": tp_stop_price,
        "notional": notional,
        "margin_usdt": margin_usdt,
        "leverage": leverage,
        "expected_net_profit": margin_usdt * tp_profit_pct + cushion_usdt,
        "estimated_fees": fees,
    }


def cancel_all_open_orders(client: Client, symbol: str) -> int:
    """진입 직전 묵은 TP/SL 주문 청소. 반환: 취소된 주문 수."""
    open_orders = client.futures_get_open_orders(symbol=symbol)
    for o in open_orders:
        try:
            client.futures_cancel_order(symbol=symbol, orderId=o["orderId"])
        except BinanceAPIException:
            pass
    return len(open_orders)
