"""트레이딩 상태 → HTML 대시보드.

다크 테마, 카드 + 표 + Chart.js 파이/라인.
GitHub Pages에서 그대로 호스팅 가능 (docs/live_dashboard.html).

state.mode 값에 따라 우상단 뱃지 자동 변경:
  - "testnet" → TESTNET (초록)
  - "mainnet" → 실거래 (빨강)
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path


def _fmt_money(x: float) -> str:
    return f"${x:,.2f}"


def _fmt_pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def _fmt_qty(x: float, decimals: int = 6) -> str:
    return f"{x:,.{decimals}f}".rstrip("0").rstrip(".") or "0"


def _mode_badge_class(mode: str) -> str:
    return {
        "testnet": "badge-testnet",
        "mainnet": "badge-mainnet",
    }.get(mode, "badge-mock")


def _mode_badge_label(mode: str) -> str:
    return {
        "testnet": "TESTNET",
        "mainnet": "실거래",
    }.get(mode, "TESTNET")


def _utc_to_kst_str(iso: str | None) -> str:
    if not iso:
        return "—"
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    kst_offset = 9 * 3600
    kst = dt.timestamp() + kst_offset
    return datetime.utcfromtimestamp(kst).strftime("%Y-%m-%d %H:%M:%S KST")


def render_dashboard(state: dict, output_path: Path) -> None:
    """state → HTML. output_path 디렉토리는 자동 생성."""
    config = state["config"]
    symbol = config["symbol"]
    initial = float(config["initial_capital"])
    cash = float(state["cash"])
    qty = float(state["position"]["qty"])
    avg_cost = float(state["position"]["avg_cost"])
    last_price = float(state.get("last_price") or 0.0)
    last_signal = float(state.get("last_signal") or 0.0)
    peak = float(state["peak_equity"])

    position_value = qty * last_price
    equity = cash + position_value
    total_pnl = equity - initial
    total_pnl_pct = total_pnl / initial if initial > 0 else 0.0
    mdd = (equity / peak - 1) if peak > 0 else 0.0

    pos_pnl = (last_price - avg_cost) * qty if qty > 0 else 0.0
    pos_pnl_pct = (last_price / avg_cost - 1) if (qty > 0 and avg_cost > 0) else 0.0

    history = state.get("history", [])
    trades = state.get("trades", [])
    recent_trades = list(reversed(trades[-15:]))

    equity_curve = [
        {"x": h["time"], "y": float(h["equity"])} for h in history
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_html(
        symbol=symbol,
        mode=state.get("mode", "testnet"),
        last_tick=state.get("last_tick"),
        last_bar_time=state.get("last_bar_time"),
        last_signal=last_signal,
        last_price=last_price,
        equity=equity,
        cash=cash,
        position_value=position_value,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        mdd=mdd,
        peak=peak,
        qty=qty,
        avg_cost=avg_cost,
        pos_pnl=pos_pnl,
        pos_pnl_pct=pos_pnl_pct,
        started_at=state.get("started_at"),
        initial=initial,
        equity_curve=equity_curve,
        recent_trades=recent_trades,
    ), encoding="utf-8")


def _html(**ctx) -> str:
    cash = ctx["cash"]
    position_value = ctx["position_value"]
    pie_data = json.dumps([
        {"label": ctx["symbol"], "value": position_value},
        {"label": "현금", "value": cash},
    ])
    equity_data = json.dumps(ctx["equity_curve"])

    pnl_class = "gain" if ctx["total_pnl"] >= 0 else "loss"
    pnl_arrow = "▲" if ctx["total_pnl"] >= 0 else "▼"

    pos_pnl_class = "gain" if ctx["pos_pnl"] >= 0 else "loss"
    pos_pnl_arrow = "▲" if ctx["pos_pnl"] >= 0 else "▼"

    last_tick_kst = _utc_to_kst_str(ctx["last_tick"])
    last_bar_kst = _utc_to_kst_str(ctx["last_bar_time"])
    started_kst = _utc_to_kst_str(ctx["started_at"])

    trades_rows = "".join(_trade_row(t) for t in ctx["recent_trades"])
    if not trades_rows:
        trades_rows = '<tr><td colspan="6" class="muted" style="text-align:center;padding:20px">아직 체결된 거래 없음</td></tr>'

    if ctx["qty"] > 0:
        position_row = f"""
        <tr>
          <td class="ticker">{html.escape(ctx["symbol"])}</td>
          <td class="num">{_fmt_qty(ctx["qty"])}</td>
          <td class="num">{_fmt_money(ctx["avg_cost"])}</td>
          <td class="num">{_fmt_money(ctx["last_price"])}</td>
          <td class="num">{_fmt_money(ctx["avg_cost"] * ctx["qty"])}</td>
          <td class="num">{_fmt_money(position_value)}</td>
          <td class="num {pos_pnl_class}">{pos_pnl_arrow} {_fmt_money(abs(ctx["pos_pnl"]))}</td>
          <td class="num {pos_pnl_class}">{pos_pnl_arrow} {_fmt_pct(ctx["pos_pnl_pct"])}</td>
        </tr>
        """
    else:
        position_row = '<tr><td colspan="8" class="muted" style="text-align:center;padding:20px">보유 포지션 없음 (전액 현금)</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>코인 자동매매 대시보드</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px;
    font-family: -apple-system, "Segoe UI", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
    background: linear-gradient(180deg,#0d111a 0%,#0f1419 100%);
    color: #e6e9ef; min-height: 100vh;
  }}
  .container {{ max-width: 1280px; margin: 0 auto; }}
  header {{
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 28px; flex-wrap: wrap; gap: 12px;
  }}
  h1 {{ margin: 0; font-size: 26px; font-weight: 700; }}
  h2 {{ margin: 0 0 16px 0; font-size: 16px; font-weight: 600; color: #c2c8d4; }}
  .updated {{ color: #8993a6; font-size: 13px; }}
  .badge {{
    display: inline-block; margin-left: 8px; padding: 4px 10px;
    border-radius: 6px; font-size: 12px; font-weight: 600;
  }}
  .badge-mock {{ background: #283042; color: #8b9ec9; }}
  .badge-testnet {{ background: #2d4a2d; color: #7fdc7f; }}
  .badge-mainnet {{ background: #4a2d2d; color: #ec5b5b; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 16px; margin-bottom: 24px;
  }}
  .card {{
    background: #1a1f2e; border: 1px solid #283042;
    border-radius: 14px; padding: 20px;
  }}
  .card-label {{ color: #8993a6; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 10px; }}
  .card-value {{ font-size: 28px; font-weight: 700; line-height: 1.1; }}
  .card-sub {{ color: #8993a6; font-size: 13px; margin-top: 8px; }}
  .gain {{ color: #36c474; }}
  .loss {{ color: #ec5b5b; }}
  .muted {{ color: #8993a6; }}
  .chart-wrap {{ background: #1a1f2e; border-radius: 14px; padding: 20px; border: 1px solid #283042; margin-bottom: 24px; }}
  .chart-wrap canvas {{ max-height: 260px !important; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ padding: 12px 10px; border-bottom: 1px solid #283042; }}
  th {{ color: #8993a6; font-size: 11px; font-weight: 600; text-transform: uppercase; text-align: left; letter-spacing: 0.5px; }}
  th.num, td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .ticker {{ font-weight: 700; }}
  tbody tr:hover {{ background: #11151f; }}
  footer {{ text-align: center; color: #5a6378; font-size: 12px; margin-top: 36px; }}
  .signal-bar {{ height: 8px; background: #283042; border-radius: 4px; overflow: hidden; margin-top: 8px; }}
  .signal-fill {{ height: 100%; background: linear-gradient(90deg,#3a4252,#5b9bd5); border-radius: 4px; }}
</style>
</head>
<body>
<div class="container">

<header>
  <h1>📊 코인 자동매매<span class="badge {_mode_badge_class(ctx["mode"])}">{_mode_badge_label(ctx["mode"])}</span></h1>
  <div class="updated">업데이트 {last_tick_kst}</div>
</header>

<div class="grid">
  <div class="card">
    <div class="card-label">💰 총자산</div>
    <div class="card-value">{_fmt_money(ctx["equity"])}</div>
    <div class="card-sub {pnl_class}">{pnl_arrow} {_fmt_money(abs(ctx["total_pnl"]))} ({_fmt_pct(ctx["total_pnl_pct"])})</div>
  </div>
  <div class="card">
    <div class="card-label">📈 {html.escape(ctx["symbol"])} 평가금액</div>
    <div class="card-value">{_fmt_money(position_value)}</div>
    <div class="card-sub">수량 {_fmt_qty(ctx["qty"])} · 현재가 {_fmt_money(ctx["last_price"])}</div>
  </div>
  <div class="card">
    <div class="card-label">💵 예수금</div>
    <div class="card-value">{_fmt_money(cash)}</div>
    <div class="card-sub">시작 {_fmt_money(ctx["initial"])}</div>
  </div>
  <div class="card">
    <div class="card-label">📉 MDD</div>
    <div class="card-value loss">{_fmt_pct(ctx["mdd"])}</div>
    <div class="card-sub">peak {_fmt_money(ctx["peak"])}</div>
  </div>
  <div class="card">
    <div class="card-label">🎯 현재 신호 (cycle_aware)</div>
    <div class="card-value">{ctx["last_signal"]:.3f}</div>
    <div class="card-sub">기준 봉 {last_bar_kst}</div>
    <div class="signal-bar"><div class="signal-fill" style="width:{min(max(ctx["last_signal"] * 100, 0), 100):.1f}%"></div></div>
  </div>
</div>

<div class="chart-wrap">
  <h2>📊 자산 추이</h2>
  <canvas id="equityChart"></canvas>
</div>

<div class="chart-wrap">
  <h2>🥧 포트폴리오 구성</h2>
  <canvas id="pieChart"></canvas>
</div>

<div class="chart-wrap">
  <h2>📦 현재 포지션</h2>
  <table>
    <thead>
      <tr>
        <th>종목</th>
        <th class="num">수량</th>
        <th class="num">평균 매수가</th>
        <th class="num">현재가</th>
        <th class="num">매수금액</th>
        <th class="num">평가금액</th>
        <th class="num">손익</th>
        <th class="num">손익률</th>
      </tr>
    </thead>
    <tbody>{position_row}</tbody>
  </table>
</div>

<div class="chart-wrap">
  <h2>🧾 최근 거래 (최대 15건)</h2>
  <table>
    <thead>
      <tr>
        <th>시간 (KST)</th>
        <th>구분</th>
        <th>종목</th>
        <th class="num">수량</th>
        <th class="num">체결가</th>
        <th class="num">금액</th>
      </tr>
    </thead>
    <tbody>{trades_rows}</tbody>
  </table>
</div>

<footer>시작일 {started_kst} · 데이터: Binance 공개 API · 전략: cycle_aware</footer>

</div>

<script>
const pieData = {pie_data};
new Chart(document.getElementById('pieChart').getContext('2d'), {{
  type: 'doughnut',
  data: {{
    labels: pieData.map(d => d.label),
    datasets: [{{
      data: pieData.map(d => d.value),
      backgroundColor: ['#5b9bd5', '#3a4252'],
      borderColor: '#1a1f2e', borderWidth: 2, hoverOffset: 8,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{
      legend: {{ position: 'right', labels: {{ color: '#e6e9ef', padding: 14, font: {{ size: 13 }} }} }},
      tooltip: {{
        callbacks: {{
          label: (ctx) => {{
            const v = ctx.parsed;
            const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
            const pct = total ? (v / total * 100).toFixed(1) : '0.0';
            return ` ${{ctx.label}}: $${{v.toLocaleString(undefined, {{maximumFractionDigits: 2}})}} (${{pct}}%)`;
          }}
        }}
      }}
    }}
  }}
}});

const equityData = {equity_data};
new Chart(document.getElementById('equityChart').getContext('2d'), {{
  type: 'line',
  data: {{
    datasets: [{{
      label: '총자산',
      data: equityData,
      borderColor: '#5b9bd5',
      backgroundColor: 'rgba(91,155,213,0.15)',
      fill: true, tension: 0.2, pointRadius: 2, pointHoverRadius: 5,
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    parsing: false,
    scales: {{
      x: {{ type: 'time', time: {{ unit: 'day' }}, ticks: {{ color: '#8993a6' }}, grid: {{ color: '#283042' }} }},
      y: {{ ticks: {{ color: '#8993a6', callback: (v) => '$' + v.toLocaleString() }}, grid: {{ color: '#283042' }} }}
    }},
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: (ctx) => ' $' + ctx.parsed.y.toLocaleString(undefined, {{maximumFractionDigits: 2}}) }} }}
    }}
  }}
}});
</script>
</body>
</html>
"""


def _trade_row(t: dict) -> str:
    side = t.get("side", "?")
    side_class = "gain" if side == "buy" else "loss"
    side_label = "매수" if side == "buy" else "매도"
    return f"""
    <tr>
      <td class="muted">{_utc_to_kst_str(t.get("time"))}</td>
      <td class="{side_class}">{side_label}</td>
      <td class="ticker">{html.escape(t.get("bar_time", "")[:10])}</td>
      <td class="num">{_fmt_qty(float(t.get("qty", 0)))}</td>
      <td class="num">{_fmt_money(float(t.get("price", 0)))}</td>
      <td class="num">{_fmt_money(float(t.get("value", 0)))}</td>
    </tr>
    """
