"""Trend Rotation 생존편향 없는 백테스트 — 라이브와 같은 함수로 재현.

src.portfolio 의 select_universe / should_drop / weights_from_signals / apply_band 를
날짜별로 그대로 호출한다. 데이터는 research/fetch_all_pairs.py 로 받은 data/all/ (상장폐지 포함).

비용: 편도 fee+slippage (기본 0.15%). 체결은 마감 봉 다음 날 수익률에 반영 (lookahead 없음).
기간: 설계 2018-09~2022 / 검증 2023~2024-10 / 홀드아웃 2024-11~

실행: python -X utf8 research/backtest_trend_rotation.py [--cash-apr 0.03] [--cost 0.0015]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.portfolio import (  # noqa: E402
    TrendRotationConfig, apply_band, select_universe, should_drop, weights_from_signals,
)
from src.portfolio.signals import trend_fraction, vol_scale  # noqa: E402

DATA = ROOT / "data" / "all"
# 데이터 점검으로 확인한 토큰 액면변경/심볼 재사용 날짜 → 이 날부터 별도 종목 취급 (가짜 수익률 방지)
BREAKS = {
    "COCOSUSDT": ["2021-01-23"], "DREPUSDT": ["2021-04-02"], "SUNUSDT": ["2021-06-18"],
    "QUICKUSDT": ["2023-07-21"], "BNXUSDT": ["2023-02-22"], "LUNAUSDT": ["2022-05-31"],
}
PERIODS = [("전체", "2018-09-01", "2100-01-01"), ("설계 18-09~22", "2018-09-01", "2023-01-01"),
           ("검증 23~24-10", "2023-01-01", "2024-11-01"), ("홀드아웃 24-11~", "2024-11-01", "2100-01-01")]


def load_segments() -> dict[str, pd.DataFrame]:
    """액면변경/장기 공백(>30일)에서 시계열을 끊어 별도 종목으로."""
    out = {}
    for path in sorted(DATA.glob("*.parquet")):
        df = pd.read_parquet(path)
        cuts = [pd.Timestamp(d, tz="UTC") for d in BREAKS.get(path.stem, [])]
        gap = df.index.to_series().diff().dt.days
        cuts += list(gap[gap > 30].index)
        bounds = [df.index.min()] + sorted(set(cuts)) + [df.index.max() + pd.Timedelta(days=1)]
        for k in range(len(bounds) - 1):
            seg = df[(df.index >= bounds[k]) & (df.index < bounds[k + 1])]
            if len(seg) >= 30:
                out[path.stem if k == 0 else f"{path.stem}#{k + 1}"] = seg
    return out


def run(cfg: TrendRotationConfig, cost: float, cash_apr: float, start="2018-09-01"):
    segs = load_segments()
    closes = pd.DataFrame({s: d["close"] for s, d in segs.items()}).sort_index()
    # 세그먼트별로 수익률 계산 → 결측일(거래 공백) 다음 날에 그 사이 가격 변화가 온전히 반영됨
    rets = pd.DataFrame({s: d["close"].pct_change(fill_method=None) for s, d in segs.items()}).reindex(closes.index)
    frac = {s: trend_fraction(d["close"], cfg.lookbacks) for s, d in segs.items()}
    size_alt = {s: vol_scale(d["close"], cfg.alt_target_vol, cfg.vol_window) for s, d in segs.items()}
    btc = segs[cfg.btc_symbol]["close"]
    size_btc = vol_scale(btc, cfg.btc_target_vol, cfg.vol_window)

    dates = closes.index[closes.index >= pd.Timestamp(start, tz="UTC") - pd.Timedelta(days=40)]
    universe: list[str] = []
    held: dict[str, float] = {}
    prev_fracs: dict[str, float] = {}
    rows = []
    for i, d in enumerate(dates[:-1]):
        # 월말(또는 첫 날) 유니버스 재선정
        if i == 0 or d.month != dates[i + 1].month:
            asof = {s: seg.loc[:d] for s, seg in segs.items() if seg.index[0] <= d <= seg.index[-1]}
            universe = select_universe(asof, cfg.alt_slots, cfg.min_listing_days, cfg.min_median_volume)
        live = [s for s in universe
                if d <= segs[s].index[-1]
                and not should_drop(segs[s].loc[:d], cfg.exit_median_volume, cfg.min_median_move)]

        btc_sig = (float(frac[cfg.btc_symbol].get(d, 0.0)), float(size_btc.get(d, 0.0)))
        alt_sigs = {s: (float(frac[s].get(d, 0.0)), float(size_alt[s].get(d, 0.0))) for s in live}
        targets, fracs = weights_from_signals(btc_sig, alt_sigs, cfg)
        new = apply_band(targets, held, fracs, prev_fracs, live, cfg)
        new = {s: w for s, w in new.items() if w > 1e-9 and d < segs[s].index[-1]}  # 상장폐지 종목은 마지막 종가에 청산
        turnover = sum(abs(new.get(s, 0.0) - held.get(s, 0.0)) for s in set(new) | set(held))
        prev_fracs = fracs

        nxt = dates[i + 1]
        r = {s: float(rets.at[nxt, s]) if not np.isnan(rets.at[nxt, s]) else 0.0 for s in new}
        gross = sum(w * r[s] for s, w in new.items())
        expo = sum(new.values())
        net = gross - turnover * cost + max(1.0 - expo, 0.0) * cash_apr / 365
        # 다음 날 시작 비중 = 가격 변동으로 드리프트
        growth = 1.0 + net  # 비용/현금이자까지 반영한 총자산 변화로 다음 날 비중 정규화
        held = {s: w * (1 + r[s]) / growth for s, w in new.items()} if growth > 0 else {}
        rows.append((nxt, net, expo, turnover, len(live)))
    res = pd.DataFrame(rows, columns=["date", "net", "expo", "turnover", "n_live"]).set_index("date")
    return res[res.index >= pd.Timestamp(start, tz="UTC")]


def stats(net: pd.Series) -> dict:
    eq = (1 + net).cumprod()
    yrs = len(net) / 365
    return {
        "CAGR": eq.iloc[-1] ** (1 / yrs) - 1,
        "Sharpe": net.mean() / net.std() * np.sqrt(365) if net.std() > 0 else 0.0,
        "MDD": (eq / eq.cummax() - 1).min(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost", type=float, default=0.0015)
    ap.add_argument("--cash-apr", type=float, default=0.0)
    args = ap.parse_args()
    if not DATA.exists():
        print("data/all/ 없음 — 먼저 python -X utf8 research/fetch_all_pairs.py")
        return 1
    cfg = TrendRotationConfig()
    res = run(cfg, args.cost, args.cash_apr)
    print(f"Trend Rotation (cost {args.cost*100:.2f}%/side, cash {args.cash_apr*100:.1f}%)")
    print(f"  평균 노출 {res['expo'].mean()*100:.1f}%, 연 회전 {res['turnover'].sum()/(len(res)/365):.1f}배, "
          f"평균 활성 알트 {res['n_live'].mean():.1f}")
    for name, a, b in PERIODS:
        m = (res.index >= pd.Timestamp(a, tz="UTC")) & (res.index < pd.Timestamp(b, tz="UTC"))
        s = stats(res["net"][m])
        print(f"  {name:16s} CAGR {s['CAGR']*100:6.1f}%  Sharpe {s['Sharpe']:5.2f}  MDD {s['MDD']*100:6.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
