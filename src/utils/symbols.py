"""심볼 유틸."""
from __future__ import annotations

QUOTE_ASSETS = ("USDT", "USDC", "BUSD", "USD", "BTC", "ETH")


def split_symbol(symbol: str) -> tuple[str, str]:
    """BTCUSDT → ('BTC', 'USDT')."""
    for quote in QUOTE_ASSETS:
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return symbol[: -len(quote)], quote
    raise ValueError(f"Cannot split symbol: {symbol}")
