"""Binance OHLCV(캔들) 데이터 수집 + 로컬 캐싱.

공개 엔드포인트만 사용하므로 API 키 없이 동작한다.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
MAX_LIMIT = 1000

INTERVAL_TO_MS = {
    "1m": 60_000,
    "3m": 3 * 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "2h": 2 * 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "6h": 6 * 60 * 60_000,
    "8h": 8 * 60 * 60_000,
    "12h": 12 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
    "3d": 3 * 24 * 60 * 60_000,
    "1w": 7 * 24 * 60 * 60_000,
}

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]

NUMERIC_COLS = ["open", "high", "low", "close", "volume",
                "quote_volume", "taker_buy_base", "taker_buy_quote"]


def _to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _last_closed_open_ms(now: datetime, interval: str) -> int:
    """interval 단위로 가장 최근에 완전히 마감된 봉의 open_time (ms).

    봉 close_time = open_time + step - 1. close_time <= now 인 봉이 마감 완료.
    → 마지막 마감 봉 open_time = floor((now - step + 1) / step) * step.
    """
    step_ms = INTERVAL_TO_MS[interval]
    now_ms = _to_ms(now)
    return ((now_ms - step_ms + 1) // step_ms) * step_ms


def _request_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": MAX_LIMIT,
    }
    resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_ohlcv(
    symbol: str,
    interval: str = "1d",
    start: datetime | None = None,
    end: datetime | None = None,
    lookback_days: int | None = None,
) -> pd.DataFrame:
    """바이낸스에서 OHLCV 캔들을 받아 DataFrame으로 반환.

    start/end가 주어지면 그 구간을, 아니면 lookback_days만큼 과거를 가져온다.
    """
    if interval not in INTERVAL_TO_MS:
        raise ValueError(f"Unsupported interval: {interval}")

    now = datetime.now(timezone.utc)
    if end is None:
        end = now
    if start is None:
        days = lookback_days if lookback_days is not None else 365
        start = end - timedelta(days=days)

    start_ms = _to_ms(start)
    end_ms = _to_ms(end)
    step_ms = INTERVAL_TO_MS[interval]

    all_rows: list = []
    cursor = start_ms
    while cursor < end_ms:
        batch = _request_klines(symbol, interval, cursor, end_ms)
        if not batch:
            break
        all_rows.extend(batch)
        last_open = batch[-1][0]
        next_cursor = last_open + step_ms
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(batch) < MAX_LIMIT:
            break
        time.sleep(0.1)

    if not all_rows:
        return pd.DataFrame(columns=KLINE_COLUMNS)

    df = pd.DataFrame(all_rows, columns=KLINE_COLUMNS)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    for col in NUMERIC_COLS:
        df[col] = pd.to_numeric(df[col])
    df["trades"] = pd.to_numeric(df["trades"]).astype("int64")
    df = df.drop(columns=["ignore"])
    df = df.set_index("open_time").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    # 미마감(진행 중) 봉 제거: close_time이 현재보다 미래면 부분 봉
    now_ts = pd.Timestamp(datetime.now(timezone.utc))
    df = df[df["close_time"] <= now_ts]
    return df


def _cache_path(cache_dir: Path, symbol: str, interval: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{symbol}_{interval}.parquet"


def load_ohlcv(
    symbol: str,
    interval: str = "1d",
    lookback_days: int = 365,
    cache_dir: str | Path = "data",
    refresh: bool = False,
) -> pd.DataFrame:
    """캐시가 있으면 읽어오고 최신 부분만 보강, 없으면 전체 수집."""
    cache_dir = Path(cache_dir)
    path = _cache_path(cache_dir, symbol, interval)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)

    if path.exists() and not refresh:
        cached = pd.read_parquet(path)
        if not cached.empty:
            step = timedelta(milliseconds=INTERVAL_TO_MS[interval])
            first_time = cached.index.min()
            last_time = cached.index.max()
            start_ts = pd.Timestamp(start)

            # 요청 구간이 캐시보다 더 과거까지면 옛날 부분 보강
            if first_time > start_ts + step:
                older = fetch_ohlcv(symbol, interval, start=start, end=first_time.to_pydatetime() - step)
                if not older.empty:
                    cached = pd.concat([older, cached])
                    cached = cached[~cached.index.duplicated(keep="last")].sort_index()

            # 최신 부분 보강: 가장 최근 마감 봉을 캐시가 못 가지고 있을 때만
            last_closed_ms = _last_closed_open_ms(end, interval)
            last_closed_open = pd.Timestamp(last_closed_ms, unit="ms", tz="UTC")
            if last_time < last_closed_open:
                new_part = fetch_ohlcv(symbol, interval, start=last_time + step, end=end)
                if not new_part.empty:
                    cached = pd.concat([cached, new_part])
                    cached = cached[~cached.index.duplicated(keep="last")].sort_index()

            cached.to_parquet(path)
            return cached.loc[cached.index >= start_ts]

    df = fetch_ohlcv(symbol, interval, start=start, end=end)
    if not df.empty:
        df.to_parquet(path)
    return df
