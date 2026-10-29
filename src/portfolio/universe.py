"""알트 슬리브 유니버스 선정 (Zarattini et al. 2025, 7.1절을 Binance 현물에 맞춤).

매월 1회:
  - Binance 현물 *USDT 페어, 스테이블/법정화폐/래핑/레버리지 토큰 제외
  - 상장(첫 일봉) 후 min_listing_days 이상
  - 최근 30일 중위 일거래대금(quote volume) >= min_median_volume
  - 30일 중위 거래대금 상위 top_n
월중 제외 (매 tick):
  - 30일 중위 거래대금 < exit_median_volume, 또는 30일 중위 |일변동| < min_median_move
"""
from __future__ import annotations

import re

import pandas as pd

EXCLUDED_BASES = {
    # 스테이블코인 / 법정화폐 / 금
    "USDC", "BUSD", "TUSD", "PAX", "USDP", "USDS", "USDSB", "DAI", "FDUSD", "UST", "USTC", "SUSD",
    "AEUR", "EURI", "XUSD", "USD1", "BFUSD", "RLUSD", "USDE", "PYUSD", "EUR", "GBP", "AUD", "TRY",
    "BRL", "RUB", "UAH", "NGN", "ZAR", "BIDR", "IDRT", "BVND", "BKRW", "PAXG", "XAUT",
    # 래핑 토큰
    "WBTC", "WBETH", "BETH",
    # 레버리지 토큰 (접미사 규칙으로 못 거르는 짧은 이름)
    "BULL", "BEAR",
}
_LEVERAGED_SUFFIX = re.compile(r"(UP|DOWN|BULL|BEAR)$")


def is_eligible_symbol(symbol: str, quote: str = "USDT") -> bool:
    if not symbol.endswith(quote):
        return False
    base = symbol[: -len(quote)]
    if not base or base in EXCLUDED_BASES:
        return False
    if len(base) > 4 and _LEVERAGED_SUFFIX.search(base):
        return False
    return True


def median_volume(quote_volume: pd.Series, window: int = 30) -> float:
    tail = quote_volume.dropna().iloc[-window:]
    return float(tail.median()) if len(tail) >= min(20, window) else 0.0


def median_abs_move(close: pd.Series, window: int = 30) -> float:
    tail = close.dropna().pct_change().abs().iloc[-window:]
    return float(tail.median()) if len(tail) >= min(20, window) else 0.0


def select_universe(
    daily: dict[str, pd.DataFrame],
    top_n: int,
    min_listing_days: int = 365,
    min_median_volume: float = 2e6,
) -> list[str]:
    """daily: {symbol: 일봉 DataFrame (close, quote_volume), as-of 시점까지}.

    첫 봉 기준 상장 기간과 30일 중위 거래대금으로 걸러 상위 top_n 반환.
    """
    ranked = []
    for sym, df in daily.items():
        if df.empty or not is_eligible_symbol(sym):
            continue
        listed_days = (df.index[-1] - df.index[0]).days
        if listed_days < min_listing_days:
            continue
        mv = median_volume(df["quote_volume"])
        if mv >= min_median_volume:
            ranked.append((mv, sym))
    ranked.sort(reverse=True)
    return [sym for _, sym in ranked[:top_n]]


def should_drop(df: pd.DataFrame, exit_median_volume: float = 1e6,
                min_median_move: float = 0.005) -> bool:
    """월중 강제 제외 조건 (유동성 고갈 / 가격 정체)."""
    if df.empty:
        return True
    return (median_volume(df["quote_volume"]) < exit_median_volume
            or median_abs_move(df["close"]) < min_median_move)
