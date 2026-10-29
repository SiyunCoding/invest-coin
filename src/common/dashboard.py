"""Trend Rotation 상태 → HTML 대시보드 (docs/live_dashboard.html).

다크 테마, 카드 + 표 + Chart.js 라인/도넛.
- 성과는 외부 입출금(testnet 잔고 리셋 등)을 제외한 NAV 기준
- BTC 단순 보유와 같은 축에 비교 (강세장에서 뒤처지는 구조적 특성을 숨기지 않음)

state.mode: "testnet" → TESTNET(초록) / "mainnet" → 실거래(빨강)
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _fmt_money(x: float) -> str:
    return f"${x:,.2f}"


def _fmt_pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def _fmt_qty(x: float, decimals: int = 6) -> str:
    return f"{x:,.{decimals}f}".rstrip("0").rstrip(".") or "0"


def _utc_to_kst_str(iso: str | None) -> str:
    if not iso:
        return "—"
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")


def render_dashboard(state: dict, output_path: Path) -> None:
    """state → HTML. output_path 디렉토리는 자동 생성."""
    history = state.get("history", [])
    last = history[-1] if history else {}
    equity = float(last.get("equity", state.get("initial_equity", 0.0)))
    weights = last.get("weights", {})
    nav = float(state.get("nav", 1.0))
    peak_nav = float(state.get("peak_nav", 1.0))
    start_btc = float(state.get("start_btc_price") or 0.0)
    btc_now = float(last.get("btc_price") or 0.0)

    holdings_rows = []
    for sym, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        holdings_rows.append({
            "symbol": sym,
            "qty": float(state.get("holdings", {}).get(sym, 0.0)),
            "value": w * equity,
            "weight": w,
            "target": float(state.get("targets", {}).get(sym, 0.0)),
            "frac": float(state.get("fracs", {}).get(sym, 0.0)),
        })

    curve = [{"x": h["time"], "nav": float(h.get("nav", 1.0)),
              "btc": (float(h["btc_price"]) / start_btc) if start_btc and h.get("btc_price") else None}
             for h in history]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_html(
        mode=state.get("mode", "testnet"),
        last_tick=state.get("last_tick"),
        last_bar_time=state.get("last_bar_time"),
        started_at=state.get("started_at"),
        equity=equity,
        cash=float(state.get("cash", 0.0)),
        exposure=float(last.get("exposure", 0.0)),
        nav_return=nav - 1,
        btc_return=(btc_now / start_btc - 1) if start_btc and btc_now else 0.0,
        mdd=nav / peak_nav - 1 if peak_nav > 0 else 0.0,
        external_flows=float(state.get("external_flows", 0.0)),
        holdings=holdings_rows,
        universe=state.get("universe", {}),
        curve=curve,
        recent_trades=list(reversed(state.get("trades", [])[-20:])),
    ), encoding="utf-8")


def _html(**ctx) -> str:
    pie = json.dumps([{"label": h["symbol"].replace("USDT", ""), "value": h["value"]} for h in ctx["holdings"]]
                     + [{"label": "현금", "value": ctx["cash"]}])
    curve = json.dumps(ctx["curve"])
    ret_class = "gain" if ctx["nav_return"] >= 0 else "loss"
    btc_class = "gain" if ctx["btc_return"] >= 0 else "loss"

    rows = "".join(
        f"""<tr><td class="ticker">{html.escape(h["symbol"])}</td>
        <td class="num">{_fmt_qty(h["qty"])}</td><td class="num">{_fmt_money(h["value"])}</td>
        <td class="num">{h["weight"]*100:.1f}%</td><td class="num">{h["target"]*100:.1f}%</td>
        <td class="num">{h["frac"]*100:.0f}%</td></tr>"""
        for h in ctx["holdings"]
    ) or '<tr><td colspan="6" class="muted center">보유 종목 없음 (전액 현금)</td></tr>'

    uni = ctx["universe"] or {}
    uni_list = ", ".join(s.replace("USDT", "") for s in uni.get("symbols", [])) or "—"
    trades = "".join(_trade_row(t) for t in ctx["recent_trades"]) \
        or '<tr><td colspan="5" class="muted center">아직 거래 없음</td></tr>'

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
  body {{ margin: 0; padding: 24px 16px; font-family: -apple-system, "Segoe UI", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
         background: #0f1419; color: #e6e9ef; }}
  .container {{ max-width: 1280px; margin: 0 auto; }}
  header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; flex-wrap: wrap; gap: 12px; }}
  h1 {{ margin: 0; font-size: 24px; }}
  h2 {{ margin: 0 0 14px 0; font-size: 16px; color: #c2c8d4; }}
  .updated, .muted {{ color: #8993a6; font-size: 13px; }}
  .center {{ text-align: center; padding: 20px; }}
  .badge {{ margin-left: 8px; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; }}
  .badge-testnet {{ background: #2d4a2d; color: #7fdc7f; }}
  .badge-mainnet {{ background: #4a2d2d; color: #ec5b5b; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin-bottom: 22px; }}
  .card, .panel {{ background: #1a1f2e; border: 1px solid #283042; border-radius: 14px; padding: 18px; }}
  .panel {{ margin-bottom: 22px; overflow-x: auto; }}
  .card-label {{ color: #8993a6; font-size: 12px; font-weight: 600; margin-bottom: 8px; }}
  .card-value {{ font-size: 26px; font-weight: 700; }}
  .card-sub {{ color: #8993a6; font-size: 13px; margin-top: 6px; }}
  .gain {{ color: #36c474; }} .loss {{ color: #ec5b5b; }}
  canvas {{ max-height: 280px !important; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ padding: 10px 8px; border-bottom: 1px solid #283042; }}
  th {{ color: #8993a6; font-size: 11px; text-align: left; }}
  th.num, td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .ticker {{ font-weight: 700; }}
  footer {{ text-align: center; color: #5a6378; font-size: 12px; margin-top: 30px; }}
</style>
</head>
<body><div class="container">
<header>
  <h1>📊 코인 자동매매<span class="badge {'badge-mainnet' if ctx['mode'] == 'mainnet' else 'badge-testnet'}">{'실거래' if ctx['mode'] == 'mainnet' else 'TESTNET'}</span></h1>
  <div class="updated">업데이트 {_utc_to_kst_str(ctx['last_tick'])} · 기준 봉 {_utc_to_kst_str(ctx['last_bar_time'])}</div>
</header>

<div class="grid">
  <div class="card"><div class="card-label">💰 총자산</div><div class="card-value">{_fmt_money(ctx['equity'])}</div>
    <div class="card-sub">현금 {_fmt_money(ctx['cash'])}</div></div>
  <div class="card"><div class="card-label">📈 전략 누적 수익 (입출금 제외)</div><div class="card-value {ret_class}">{_fmt_pct(ctx['nav_return'])}</div>
    <div class="card-sub">같은 기간 BTC 보유 <span class="{btc_class}">{_fmt_pct(ctx['btc_return'])}</span></div></div>
  <div class="card"><div class="card-label">🎯 시장 노출</div><div class="card-value">{ctx['exposure']*100:.1f}%</div>
    <div class="card-sub">나머지는 USDT 현금</div></div>
  <div class="card"><div class="card-label">📉 MDD (NAV)</div><div class="card-value loss">{_fmt_pct(ctx['mdd'])}</div>
    <div class="card-sub">외부 입출금 누적 {_fmt_money(ctx['external_flows'])}</div></div>
</div>

<div class="panel"><h2>📊 전략 NAV vs BTC 보유 (시작=1.0)</h2><canvas id="navChart"></canvas></div>
<div class="panel"><h2>🥧 구성</h2><canvas id="pieChart"></canvas></div>

<div class="panel"><h2>📦 보유 종목</h2>
<table><thead><tr><th>종목</th><th class="num">수량</th><th class="num">평가금액</th><th class="num">현재 비중</th>
<th class="num">목표 비중</th><th class="num">추세 신호</th></tr></thead><tbody>{rows}</tbody></table>
<div class="muted" style="margin-top:12px">알트 유니버스 ({_utc_to_kst_str(uni.get('selected_at'))} 선정): {html.escape(uni_list)}</div>
</div>

<div class="panel"><h2>🧾 최근 거래 (최대 20건)</h2>
<table><thead><tr><th>시간</th><th>구분</th><th>종목</th><th class="num">수량</th><th class="num">금액</th></tr></thead>
<tbody>{trades}</tbody></table></div>

<footer>시작 {_utc_to_kst_str(ctx['started_at'])} · 전략: Trend Rotation (Donchian 앙상블, BTC 50% + 알트 상위 10) · 데이터: Binance</footer>
</div>
<script>
const curve = {curve};
new Chart(document.getElementById('navChart'), {{
  type: 'line',
  data: {{ datasets: [
    {{ label: '전략 NAV', data: curve.map(p => ({{x: p.x, y: p.nav}})), borderColor: '#5b9bd5', pointRadius: 0, tension: 0.2 }},
    {{ label: 'BTC 보유', data: curve.filter(p => p.btc !== null).map(p => ({{x: p.x, y: p.btc}})), borderColor: '#d59b5b', pointRadius: 0, borderDash: [4, 4] }},
  ] }},
  options: {{ responsive: true, maintainAspectRatio: false, parsing: false,
    scales: {{ x: {{ type: 'time', ticks: {{ color: '#8993a6' }}, grid: {{ color: '#283042' }} }},
               y: {{ ticks: {{ color: '#8993a6' }}, grid: {{ color: '#283042' }} }} }},
    plugins: {{ legend: {{ labels: {{ color: '#e6e9ef' }} }} }} }}
}});
const pie = {pie};
new Chart(document.getElementById('pieChart'), {{
  type: 'doughnut',
  data: {{ labels: pie.map(d => d.label), datasets: [{{ data: pie.map(d => d.value), borderColor: '#1a1f2e' }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'right', labels: {{ color: '#e6e9ef' }} }} }} }}
}});
</script>
</body></html>
"""


def _trade_row(t: dict) -> str:
    side = t.get("side", "?")
    cls, label = {"buy": ("gain", "매수"), "sell": ("loss", "매도"),
                  "error": ("muted", "오류"), "halted": ("loss", "정지")}.get(side, ("muted", side))
    if side == "halted":
        detail = html.escape("; ".join(t.get("reasons", [])))
        return f'<tr><td class="muted">{_utc_to_kst_str(t.get("time"))}</td><td class="{cls}">{label}</td><td colspan="3" class="muted">{detail}</td></tr>'
    if side == "error":
        detail = html.escape(f"{t.get('attempted', '')} {t.get('error_code', '')} {t.get('error_message', '')}")
        return f'<tr><td class="muted">{_utc_to_kst_str(t.get("time"))}</td><td class="{cls}">{label}</td><td class="ticker">{html.escape(t.get("symbol", ""))}</td><td colspan="2" class="muted">{detail}</td></tr>'
    return (f'<tr><td class="muted">{_utc_to_kst_str(t.get("time"))}</td><td class="{cls}">{label}</td>'
            f'<td class="ticker">{html.escape(t.get("symbol", ""))}</td><td class="num">{_fmt_qty(float(t.get("qty", 0)))}</td>'
            f'<td class="num">{_fmt_money(float(t.get("value", 0)))}</td></tr>')
