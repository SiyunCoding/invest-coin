# Invest Coin — 바이낸스 현물 자동매매

Binance 현물에서 매일 1회 리밸런스하는 추세추종 포트폴리오 봇.
**백테스트 → Testnet(가짜 돈, 진짜 API) → 실거래** 순으로 단계적 확장.

## 진행 단계

- ✅ Phase 1~3 백테스트 시스템 + 전략 10종 + multi-regime 검증 (연구 기록은 `tasks/lessons.md`)
- ✅ Phase 4 Binance Testnet 자동매매 (Oracle Cloud self-hosted runner, 매일 cron, Telegram)
- ✅ Phase 4.6 전략 교체: cycle_aware → **Trend Rotation** (2026-10, 문헌 조사 + 생존편향 없는 검증)
- ✅ Phase 4.7 품질·보안 정비 (2026-10, 리뷰 4종 + 교차검증)
- 🔮 Phase 5 실거래 (testnet 2~4주 관찰 후)

## 현재 전략 — Trend Rotation

**BTC 50% 슬리브 + 월간 알트 상위 10 슬리브**, 종목마다 Donchian 앙상블 추세추종
(Zarattini/Pagani/Barbon 2025 "Catching Crypto Trends" Combo) + 변동성 타깃.

```
종목별 신호 frac = 보유 중인 Donchian 기간 비율, 기간 {5,10,20,30,60,90,150,250,360}일
  진입: 종가 = n일 최고 종가 / 손절선: 중앙값 래칫(내려가지 않음) / 청산: 종가 < 손절선
BTC 슬리브 비중   = 0.5 × frac × min(0.40/σ90, 1)
알트 슬롯 비중    = 0.05 × frac × min(0.60/σ90, 1)   (월말 유니버스 상위 10, 1/10씩)
유니버스: 상장 365일↑, 30일 중위 거래대금 $2M↑, 스테이블/레버리지/래핑 제외, 거래대금 순
리밸런스: 추세 신호 변화 즉시 / 변동성 변화는 슬롯 대비 20% 넘을 때만
```

**생존편향 없는 백테스트** (상장폐지 195개 포함 681개 페어, 편도 비용 0.15%, `research/backtest_trend_rotation.py`):

| | 구 cycle_aware | **Trend Rotation** | BTC 보유 |
|---|---|---|---|
| CAGR (2018-09~2026-10) | 21.9% | 22.8% (현금 3% 운용 시 25.6%) | 35.0% |
| Sharpe | 1.06 | **1.14** (1.26) | 0.80 |
| MDD | −28.4% | −28.2% (−24.8%) | −76.6% |
| 설계/검증/홀드아웃 Sharpe | 1.32 / 0.72 / 0.79 | 1.33 / 1.31 / 0.51 | |
| 파라미터 섭동 시 Sharpe 범위 | 0.07 ~ 1.17 | 1.15 ~ 1.27 | |

- 교체 이유는 수익률이 아니라 **근거와 견고성** (구 전략은 파라미터를 조금만 바꿔도 무너짐 = 과적합 신호)
- 부트스트랩상 더 나을 확률 76% (95% 유의 아님) — 8년 데이터로 확정 불가
- 구조적 한계: 강세장에선 BTC 보유보다 덜 벎 (평균 노출 ~26%). 폭락장 방어가 대가
- 근거·교차검증: `tasks/lessons.md` L12~L16

## 프로젝트 구조

```
scripts/live_tick.py              ★ 실매매 엔트리 (GitHub Actions 가 매일 실행)
src/
├── live/                         실매매
│   ├── client.py                 testnet/mainnet Binance Client
│   ├── portfolio_tick.py         잔고→유니버스→신호→안전장치→주문→state/대시보드/알림
│   └── portfolio_executor.py     멀티코인 리밸런스 (매도→매수, 거래소 규칙, 수량 포맷)
├── portfolio/                    전략 핵심 (백테스트·라이브 공용 — 연구 코드와 분리)
│   ├── signals.py                Donchian 앙상블 신호 / 변동성
│   ├── universe.py               유니버스 선정 / 월중 제외
│   └── allocator.py              목표 비중 + 리밸런스 밴드
├── common/                       state JSON, HTML 대시보드
├── notifier/telegram.py          Telegram 알림 (토큰 로그 마스킹)
├── data/binance_data.py          OHLCV 수집 + 캐시 (라이브는 대체 데이터 폴백 금지)
├── utils/                        지표, 심볼, 시간 표시
├── strategies/                   연구용 전략 10종 (REGISTRY, Streamlit/백테스트용)
├── backtest/                     단일 자산 백테스트 엔진/지표/최적화
└── ui/app.py                     Streamlit 연구 대시보드
research/                         연구·검증 스크립트 (실매매와 무관)
├── backtest_trend_rotation.py    생존편향 없는 Trend Rotation 백테스트 (라이브와 같은 함수)
├── fetch_all_pairs.py            상장폐지 포함 전체 USDT 페어 일봉 → data/all/
├── validate_5y.py, grid_search.py, smoke_test.py
tests/                            pytest (가짜 거래소 통합 테스트 포함, 워크플로우 게이트)
config/
├── config.yaml                   Streamlit 기본 파라미터
└── live_trading.example.yaml     실거래 전환용 예시 (복사해서 live_trading.yaml)
.github/
├── workflows/live_trading.yml    매일 tick (self-hosted runner)
├── workflows/watchdog.yml        30시간 tick 없으면 Telegram 경보 (GitHub hosted)
└── dependabot.yml                의존성/액션 업데이트 제안
data/live_state.json, docs/live_dashboard.html   봇이 매일 커밋하는 상태/대시보드
```

## 실행

```powershell
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt            # 실매매 + 테스트 (버전 고정)
pip install -r requirements-research.txt   # + Streamlit 연구 UI

pytest -q                                  # 테스트
python -X utf8 scripts/live_tick.py        # 실매매 1회 (환경변수 키 필요, .env.example 참고)
python -X utf8 research/fetch_all_pairs.py ; python -X utf8 research/backtest_trend_rotation.py
streamlit run src/ui/app.py                # 연구 UI
```

> 콘솔 한글이 깨지면 `python -X utf8`.

## 운영

### 매일 동작
- **스케줄**: 매일 UTC 00:35 예약 (GitHub 지연으로 실제 UTC 05~06시경), 어제 마감 봉 기준
- **순서**: 테스트 → 잔고 조회 → (월말 이후 첫 tick 이면) 유니버스 재선정 → 목표 비중 → 매도 → 매수 → state/대시보드 커밋
- **알림**: 매 tick Telegram (리밸런스/변함없음/정지/오류). 워크플로우 실패 시 🚨, 30시간 tick 없으면 ⏰
- **캐시/백업**: 서버 `~/.invest-coin/` (러너 작업 폴더는 매 실행 초기화되므로)

### 안전장치

| 보호 | 동작 |
|---|---|
| 테스트 게이트 | pytest 실패 시 매매 안 함 |
| 거래소 규칙 | LOT_SIZE/MARKET_LOT_SIZE 내림, MIN_NOTIONAL 미달 생략, 수량은 고정소수 문자열 |
| 주문 순서 | 매도 먼저, 매수는 매번 USDT 재조회 후 |
| 같은 봉 방어 | `last_bar_time` 으로 같은 봉 두 번 매매 안 함 |
| 리밸런스 밴드 | 변동성 때문만의 비중 변화는 슬롯 대비 20% 넘을 때만 |
| 손실 한도 | 직전 tick 대비 −5% 이하면 **매수만** 중지 (청산·축소는 허용) |
| 이상 목표/데이터 | NaN·음수·총합>100% 면 중지, BTC 데이터 오래되면 중지, 끊긴 종목은 제외 |
| 체결 실패 내성 | 한 종목 실패해도 나머지 계속, 주문 후 단계가 죽어도 state 저장 후 다음 tick 재동기화 |
| 외부 입출금 | testnet 잔고 리셋 등은 NAV 에서 제외 |
| 소액 계좌 | 총자산 < $3,000 이면 BTC 단독 (켜졌다 꺼졌다 방지 10% 히스테리시스) |
| 비상정지 | 서버에서 `touch ~/.invest-coin.halt` 또는 저장소 루트에 `.halt` 커밋 → 모든 주문 중지 (해제는 삭제) |

### GitHub Secrets
`BINANCE_TESTNET_API_KEY`, `BINANCE_TESTNET_API_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
(실거래 시 `BINANCE_API_KEY`, `BINANCE_API_SECRET` — mainnet 모드일 때만 프로세스에 전달됨)

### 서버 (Oracle Cloud Always Free, 춘천 리전)
Binance 는 GitHub hosted runner(US IP)를 451 로 차단 → 한국 IP 서버에 self-hosted runner 필수.
Ubuntu 22.04 + `python3.11` + `python3.11-venv`, runner 라벨 `self-hosted,linux,x64`.

## 보안 체크리스트 (저장소 소유자가 직접)

이 저장소는 **공개(PUBLIC)** 이고 매매 서버(self-hosted runner)가 붙어 있다. 실거래 전 필수:

1. **저장소를 Private 으로 전환** (Settings → General → Danger Zone → Change visibility) — 외부 PR 코드가 서버에서 실행될 위험 + 잔고/포지션 공개 문제를 한 번에 해결
2. Settings → Actions → General
   - Fork pull request workflows: **Require approval for all external contributors**
   - Workflow permissions: **Read repository contents** (워크플로우가 필요한 job 에서만 write 요청)
3. Settings → Rules → main 에 "Block force pushes"
4. Binance API 키: Reading + Spot Trading 만, **출금/선물/마진 OFF**, **IP 제한 = 서버 IP**, BNB 수수료 차감 OFF
5. 실거래 전까지 `BINANCE_API_KEY/SECRET` secret 은 비워 두거나, 등록돼 있던 키는 재발급

## 실거래 전환

1. 위 보안 체크리스트 완료
2. `config/live_trading.example.yaml` → `config/live_trading.yaml` 복사 (`testnet: false`)
3. 계좌 입금 ($3,000 미만이면 BTC 단독)
4. 전환 시 testnet state 는 서버 `~/.invest-coin/backups/` 에 자동 백업되고 새로 시작
