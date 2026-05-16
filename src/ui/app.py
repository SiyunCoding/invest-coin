"""Streamlit 대시보드 — 단일 백테스트 / 파라미터 최적화 / 멀티 코인 비교.

실행:
    streamlit run src/ui/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yaml
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest import grid_search, run_backtest, run_multi_coin  # noqa: E402
from src.data import load_ohlcv  # noqa: E402
from src.strategies import REGISTRY, ParamSpec  # noqa: E402

CONFIG_PATH = ROOT / "config" / "config.yaml"
CACHE_DIR = ROOT / "data"

METRIC_LABELS = {
    "sharpe": "샤프",
    "total_return": "총 수익률",
    "cagr": "CAGR",
    "max_drawdown": "MDD",
}


@st.cache_data(show_spinner=False)
def _load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


@st.cache_data(show_spinner="시장 데이터 불러오는 중...")
def _cached_load_ohlcv(symbol: str, interval: str, lookback_days: int, refresh: bool) -> pd.DataFrame:
    return load_ohlcv(
        symbol=symbol, interval=interval,
        lookback_days=lookback_days, cache_dir=CACHE_DIR, refresh=refresh,
    )


def _fmt_pct(x: float) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x * 100:.2f}%"


def _param_widget(spec: ParamSpec, key: str, default=None):
    """ParamSpec → Streamlit 위젯. key로 위젯 충돌 방지."""
    value = default if default is not None else spec.default
    if spec.kind == "bool":
        return st.checkbox(spec.label, value=bool(value), help=spec.help, key=key)
    if spec.kind == "int":
        return st.slider(
            spec.label, min_value=int(spec.min), max_value=int(spec.max),
            value=int(value), step=int(spec.step), help=spec.help, key=key,
        )
    return st.slider(
        spec.label, min_value=float(spec.min), max_value=float(spec.max),
        value=float(value), step=float(spec.step), help=spec.help, key=key,
    )


def _range_widget(spec: ParamSpec, key: str):
    """optimizer용 범위 위젯 (min~max). 그리드 step도 같이 받음."""
    if spec.kind == "bool":
        # bool은 그리드가 무의미 → 고정 디폴트 사용
        st.caption(f"{spec.label}: {bool(spec.default)} (그리드 비활성)")
        return [bool(spec.default)]
    cols = st.columns([3, 1])
    with cols[0]:
        if spec.kind == "int":
            lo, hi = st.slider(
                f"{spec.label} 범위", min_value=int(spec.min), max_value=int(spec.max),
                value=(int(spec.min), int(spec.max)), step=int(spec.step),
                help=spec.help, key=key + "_range",
            )
        else:
            lo, hi = st.slider(
                f"{spec.label} 범위", min_value=float(spec.min), max_value=float(spec.max),
                value=(float(spec.min), float(spec.max)), step=float(spec.step),
                help=spec.help, key=key + "_range",
            )
    with cols[1]:
        step = st.number_input(
            "step", min_value=float(spec.step), value=float(spec.step) * 2,
            step=float(spec.step), key=key + "_step",
        )
    if spec.kind == "int":
        values = list(range(int(lo), int(hi) + 1, max(int(round(step)), 1)))
    else:
        values = list(np.round(np.arange(lo, hi + step / 2, step), 4))
    return values


def _market_data_sidebar(data_cfg: dict) -> tuple[str, str, int, bool]:
    st.sidebar.header("📦 시장 데이터")
    symbol = st.sidebar.text_input(
        "심볼", value=data_cfg.get("default_symbol", "BTCUSDT"),
        help="바이낸스 심볼. 예: BTCUSDT, ETHUSDT, SOLUSDT",
    ).strip().upper()
    interval = st.sidebar.selectbox(
        "캔들 간격", options=["1d", "4h", "1h", "15m"], index=0,
        help="일봉(1d)이 가장 안정적. 짧은 봉일수록 노이즈/수수료 영향 큼.",
    )
    lookback_days = st.sidebar.slider(
        "조회 기간 (일)", min_value=30, max_value=1460,
        value=int(data_cfg.get("default_lookback_days", 365)), step=30,
    )
    refresh = st.sidebar.checkbox("캐시 무시하고 새로 받기", value=False)
    return symbol, interval, lookback_days, refresh


def _backtest_settings_sidebar(bt_cfg: dict) -> tuple[float, float, float]:
    st.sidebar.divider()
    st.sidebar.subheader("💰 백테스트 설정")
    initial_capital = st.sidebar.number_input(
        "초기 자본 (USDT)", min_value=100.0,
        value=float(bt_cfg.get("initial_capital", 10_000.0)), step=1000.0,
    )
    fee_rate = st.sidebar.number_input(
        "수수료율", min_value=0.0, max_value=0.01,
        value=float(bt_cfg.get("fee_rate", 0.001)), step=0.0005, format="%.4f",
    )
    slippage_rate = st.sidebar.number_input(
        "슬리피지율", min_value=0.0, max_value=0.01,
        value=float(bt_cfg.get("slippage_rate", 0.0005)), step=0.0005, format="%.4f",
    )
    return initial_capital, fee_rate, slippage_rate


def _strategy_selector(label_prefix: str = "") -> str:
    options = list(REGISTRY.keys())
    return st.selectbox(
        f"{label_prefix}전략",
        options=options,
        format_func=lambda k: REGISTRY[k].label,
        key=f"strategy_{label_prefix}",
    )


def _build_main_chart(result) -> go.Figure:
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.65, 0.35], vertical_spacing=0.05,
        subplot_titles=("가격 + 매매 시점", "자산 곡선"),
    )
    ohlcv = result.ohlcv
    fig.add_trace(
        go.Candlestick(
            x=ohlcv.index, open=ohlcv["open"], high=ohlcv["high"],
            low=ohlcv["low"], close=ohlcv["close"],
            name="OHLC", showlegend=False,
        ),
        row=1, col=1,
    )
    trades = result.trades
    if not trades.empty:
        fig.add_trace(
            go.Scatter(
                x=trades["entry_time"], y=trades["entry_price"],
                mode="markers", name="매수",
                marker=dict(color="#22c55e", size=10, symbol="triangle-up"),
            ), row=1, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=trades["exit_time"], y=trades["exit_price"],
                mode="markers", name="매도",
                marker=dict(color="#ef4444", size=10, symbol="triangle-down"),
            ), row=1, col=1,
        )
    fig.add_trace(
        go.Scatter(
            x=result.equity.index, y=result.equity.values,
            mode="lines", name="자산", line=dict(color="#3b82f6", width=2),
        ), row=2, col=1,
    )
    fig.update_layout(
        height=720, xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    fig.update_yaxes(title_text="가격 (USDT)", row=1, col=1)
    fig.update_yaxes(title_text="자산 (USDT)", row=2, col=1)
    return fig


# ────────────────────────────────────────────────────────── 탭 1: 단일 백테스트
def _tab_single(symbol, interval, lookback_days, refresh,
                initial_capital, fee_rate, slippage_rate, strat_cfg) -> None:
    st.subheader("📈 단일 백테스트")
    strategy_name = _strategy_selector()
    meta = REGISTRY[strategy_name]

    params: dict = {}
    defaults_from_yaml = strat_cfg.get(strategy_name, {})
    cols = st.columns(min(len(meta.params), 3) or 1)
    for i, spec in enumerate(meta.params):
        with cols[i % len(cols)]:
            params[spec.name] = _param_widget(
                spec, key=f"single_{strategy_name}_{spec.name}",
                default=defaults_from_yaml.get(spec.name),
            )

    if not st.button("▶ 백테스트 실행", type="primary", key="run_single"):
        st.info("위 설정을 조정한 뒤 **백테스트 실행**을 누르세요.")
        return

    try:
        ohlcv = _cached_load_ohlcv(symbol, interval, lookback_days, refresh)
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return
    if ohlcv.empty:
        st.warning("해당 조건의 데이터가 없습니다.")
        return

    try:
        strategy = meta.cls(**params)
    except ValueError as e:
        st.error(f"전략 파라미터 오류: {e}")
        return

    with st.spinner("백테스트 실행 중..."):
        result = run_backtest(
            ohlcv=ohlcv, strategy=strategy,
            initial_capital=initial_capital,
            fee_rate=fee_rate, slippage_rate=slippage_rate,
        )

    m = result.metrics
    cols = st.columns(6)
    cols[0].metric("총 수익률", _fmt_pct(m["total_return"]))
    cols[1].metric("CAGR", _fmt_pct(m["cagr"]))
    cols[2].metric("MDD", _fmt_pct(m["max_drawdown"]))
    cols[3].metric("샤프", f"{m['sharpe']:.2f}")
    cols[4].metric("승률", _fmt_pct(m["win_rate"]))
    cols[5].metric("거래 수", m["num_trades"])

    bh = float(ohlcv["close"].iloc[-1] / ohlcv["close"].iloc[0] - 1)
    delta = m["total_return"] - bh
    st.caption(
        f"📊 같은 기간 단순보유 수익률: **{_fmt_pct(bh)}** "
        f"(전략 - 보유 = **{_fmt_pct(delta)}**)"
    )

    st.plotly_chart(_build_main_chart(result), use_container_width=True)

    with st.expander(f"📋 거래 내역 ({len(result.trades)}건)"):
        if result.trades.empty:
            st.write("거래가 없습니다.")
        else:
            df = result.trades.copy()
            df["gross_return"] = df["gross_return"].apply(_fmt_pct)
            df["net_return"] = df["net_return"].apply(_fmt_pct)
            st.dataframe(df, use_container_width=True, hide_index=True)


# ────────────────────────────────────────────────────────── 탭 2: 파라미터 최적화
def _tab_optimizer(symbol, interval, lookback_days, refresh,
                   initial_capital, fee_rate, slippage_rate) -> None:
    st.subheader("🔎 파라미터 최적화 (그리드 서치)")
    st.caption("선택한 전략의 모든 파라미터 조합을 백테스트하고 지표 기준으로 정렬합니다.")

    strategy_name = _strategy_selector("[옵티마이저] ")
    meta = REGISTRY[strategy_name]

    grid: dict = {}
    for spec in meta.params:
        grid[spec.name] = _range_widget(spec, key=f"opt_{strategy_name}_{spec.name}")

    cols = st.columns([2, 2, 1])
    with cols[0]:
        metric = st.selectbox(
            "최적화 기준", options=list(METRIC_LABELS.keys()),
            format_func=lambda k: METRIC_LABELS[k], index=0,
            key="opt_metric",
        )
    total = int(np.prod([len(v) for v in grid.values()]))
    cols[1].metric("탐색 조합 수", total)
    run = cols[2].button("▶ 최적화 실행", type="primary", key="run_opt")

    if total > 500:
        st.warning(f"조합이 {total}개로 많습니다. 시간이 오래 걸릴 수 있어요. step을 키워 줄여보세요.")

    if not run:
        return

    try:
        ohlcv = _cached_load_ohlcv(symbol, interval, lookback_days, refresh)
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return
    if ohlcv.empty:
        st.warning("해당 조건의 데이터가 없습니다.")
        return

    with st.spinner(f"{total}개 조합 백테스트 중..."):
        opt = grid_search(
            ohlcv=ohlcv, strategy_name=strategy_name, grid=grid, metric=metric,
            initial_capital=initial_capital,
            fee_rate=fee_rate, slippage_rate=slippage_rate,
        )

    st.success(f"최적 파라미터 ({METRIC_LABELS[metric]} 기준): {opt.best_params}")
    df = opt.table.copy()
    for col in ["total_return", "cagr", "max_drawdown", "win_rate"]:
        if col in df.columns:
            df[col] = df[col].apply(_fmt_pct)
    if "sharpe" in df.columns:
        df["sharpe"] = df["sharpe"].astype(float).round(2)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # 2-param 케이스: 히트맵
    param_names = list(grid.keys())
    if len(param_names) == 2 and metric in opt.table.columns:
        pivot = opt.table.pivot_table(
            index=param_names[1], columns=param_names[0], values=metric, aggfunc="mean",
        )
        fig = px.imshow(
            pivot, aspect="auto",
            color_continuous_scale="RdYlGn",
            labels=dict(color=METRIC_LABELS[metric]),
            title=f"히트맵: {param_names[0]} × {param_names[1]} → {METRIC_LABELS[metric]}",
        )
        st.plotly_chart(fig, use_container_width=True)


# ────────────────────────────────────────────────────────── 탭 3: 멀티 코인 비교
def _tab_multi_coin(interval, lookback_days, refresh,
                    initial_capital, fee_rate, slippage_rate, strat_cfg) -> None:
    st.subheader("🌐 멀티 코인 비교")
    st.caption("여러 코인에 같은 전략/파라미터를 적용해 동시 비교합니다.")

    symbols_str = st.text_input(
        "심볼 목록 (콤마로 구분)", value="BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT",
        key="mc_symbols",
    )
    symbols = [s.strip().upper() for s in symbols_str.split(",") if s.strip()]

    strategy_name = _strategy_selector("[멀티] ")
    meta = REGISTRY[strategy_name]
    defaults_from_yaml = strat_cfg.get(strategy_name, {})

    params: dict = {}
    cols = st.columns(min(len(meta.params), 3) or 1)
    for i, spec in enumerate(meta.params):
        with cols[i % len(cols)]:
            params[spec.name] = _param_widget(
                spec, key=f"mc_{strategy_name}_{spec.name}",
                default=defaults_from_yaml.get(spec.name),
            )

    if not st.button("▶ 비교 실행", type="primary", key="run_mc"):
        return

    if not symbols:
        st.warning("심볼을 1개 이상 입력하세요.")
        return

    with st.spinner(f"{len(symbols)}개 코인 백테스트 중..."):
        mc = run_multi_coin(
            symbols=symbols, strategy_name=strategy_name, strategy_params=params,
            interval=interval, lookback_days=lookback_days, cache_dir=str(CACHE_DIR),
            initial_capital=initial_capital,
            fee_rate=fee_rate, slippage_rate=slippage_rate, refresh=refresh,
        )

    if mc.summary.empty:
        st.warning("결과가 없습니다.")
        return

    df = mc.summary.copy()
    for col in ["total_return", "cagr", "max_drawdown", "win_rate", "buy_and_hold", "vs_bh"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda v: _fmt_pct(v) if isinstance(v, (int, float)) else v)
    if "sharpe" in df.columns:
        df["sharpe"] = df["sharpe"].apply(lambda v: round(v, 2) if isinstance(v, (int, float)) else v)
    st.dataframe(df, use_container_width=True, hide_index=True)

    if not mc.equity_curves.empty:
        normed = mc.equity_curves / mc.equity_curves.iloc[0]
        fig = px.line(
            normed, title="자산 곡선 (시작=1.0 기준 정규화)",
            labels={"value": "자산 (정규화)", "open_time": "시각", "variable": "코인"},
        )
        fig.update_layout(height=480, margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)


def main() -> None:
    st.set_page_config(page_title="Invest Coin — 백테스터", layout="wide")
    st.title("Invest Coin — 백테스트 대시보드")
    st.caption("Phase 2: 다중 전략 + 파라미터 최적화 + 멀티 코인 비교")

    config = _load_config()
    data_cfg = config.get("data", {})
    bt_cfg = config.get("backtest", {})
    strat_cfg = config.get("strategy", {})

    symbol, interval, lookback_days, refresh = _market_data_sidebar(data_cfg)
    initial_capital, fee_rate, slippage_rate = _backtest_settings_sidebar(bt_cfg)

    tab1, tab2, tab3 = st.tabs(["📈 단일 백테스트", "🔎 파라미터 최적화", "🌐 멀티 코인 비교"])
    with tab1:
        _tab_single(symbol, interval, lookback_days, refresh,
                    initial_capital, fee_rate, slippage_rate, strat_cfg)
    with tab2:
        _tab_optimizer(symbol, interval, lookback_days, refresh,
                       initial_capital, fee_rate, slippage_rate)
    with tab3:
        _tab_multi_coin(interval, lookback_days, refresh,
                        initial_capital, fee_rate, slippage_rate, strat_cfg)


if __name__ == "__main__":
    main()