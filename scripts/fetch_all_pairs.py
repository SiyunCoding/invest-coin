"""바이낸스에 상장됐던 모든 USDT 현물 페어 일봉 수집 (상장폐지 포함) → data/all/.

생존편향 없는 백테스트(scripts/backtest_trend_rotation.py)용.
심볼 목록: data.binance.vision S3 (과거 전체), 데이터: /api/v3/klines, 없으면 S3 월별 zip.

실행: python -X utf8 scripts/fetch_all_pairs.py   (최초 ~15분, 이후엔 받은 파일 건너뜀)
"""
from __future__ import annotations

import io
import re
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.portfolio.universe import is_eligible_symbol  # noqa: E402

OUT = ROOT / "data" / "all"
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
KLINES = "https://api.binance.com/api/v3/klines"
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
        "quote_volume", "trades", "tbb", "tbq", "ignore"]


def list_symbols() -> list[str]:
    syms, marker = [], ""
    while True:
        body = requests.get(S3, params={"prefix": "data/spot/monthly/klines/", "delimiter": "/",
                                        "marker": marker}, timeout=30).text
        found = re.findall(r"<Prefix>data/spot/monthly/klines/([^<]+)/</Prefix>", body)
        syms += found
        if "<IsTruncated>true" not in body or not found:
            break
        marker = f"data/spot/monthly/klines/{found[-1]}/"
    return sorted(set(syms))


def from_api(sym: str) -> list:
    rows, start = [], 1_500_000_000_000
    while True:
        r = requests.get(KLINES, params={"symbol": sym, "interval": "1d", "startTime": start,
                                         "limit": 1000}, timeout=20)
        if r.status_code != 200:
            return rows
        batch = r.json()
        if not batch:
            break
        rows += batch
        start = batch[-1][0] + 86_400_000
        if len(batch) < 1000:
            break
        time.sleep(0.05)
    return rows


def from_s3(sym: str) -> list:
    body = requests.get(S3, params={"prefix": f"data/spot/monthly/klines/{sym}/1d/"}, timeout=30).text
    rows = []
    for key in re.findall(r"<Key>([^<]+\.zip)</Key>", body):
        z = zipfile.ZipFile(io.BytesIO(requests.get(f"https://data.binance.vision/{key}", timeout=30).content))
        for name in z.namelist():
            rows += pd.read_csv(z.open(name), header=None).values.tolist()
    return rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    syms = [s for s in list_symbols() if is_eligible_symbol(s)]
    print(f"[fetch] eligible USDT symbols: {len(syms)}")
    saved = 0
    for sym in syms:
        path = OUT / f"{sym}.parquet"
        if path.exists():
            continue
        try:
            rows = from_api(sym) or from_s3(sym)
            if not rows:
                print(f"[fetch] empty {sym}")
                continue
            df = pd.DataFrame(rows, columns=COLS)
            ot = pd.to_numeric(df["open_time"])
            ot = ot.where(ot < 1e14, ot // 1000)  # S3 2025+ 파일은 마이크로초
            df.index = pd.to_datetime(ot, unit="ms", utc=True)
            df = df[["open", "high", "low", "close", "quote_volume"]].astype(float)
            df = df[~df.index.duplicated()].sort_index()
            df.to_parquet(path)
            saved += 1
        except Exception as e:  # 한 종목 실패가 전체를 멈추지 않게
            print(f"[fetch] fail {sym}: {e}")
    print(f"[fetch] saved {saved} new files → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
