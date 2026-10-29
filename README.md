# Invest Coin — 바이낸스 자동거래 시스템

Python + Streamlit 기반 암호화폐 자동거래.
**1단계 백테스팅 → 2단계 Testnet (가짜 돈, 진짜 API) → 3단계 실거래** 순으로 단계적 확장.

## 현재 진행 단계

- ✅ **Phase 1** 백테스팅 시스템 + Streamlit 대시보드 + 변동성 돌파 전략
- ✅ **Phase 2** 전략 확장 (MA cross / RSI), 그리드 서치, 멀티 코인 비교
- ✅ **Phase 3** 신규 전략 (CRSI / Donchian-ATR / TSMOM / Larry-ATR / 앙상블 / Cycle-Aware) + 5년 multi-regime 검증
- ✅ **Phase 4** Binance Testnet 실 매매 (Oracle Cloud self-hosted runner, 매일 자동 cron, Telegram 알림)
- ✅ **Phase 4.6** 전략 교체: cycle_aware → **Trend Rotation** (2026-10, 문헌 조사 + 생존편향 없는 검증)
- 🔮 **Phase 5** 실거래 (Testnet 통과 + 안전장치 추가 후)

## 🏆 현재 전략 — Trend Rotation (2026-10 교체)

**BTC 50% 슬리브 + 월간 알트 상위 10 슬리브**, 각 종목에 Donchian 앙상블 추세추종
(Zarattini/Pagani/Barbon 2025 "Catching Crypto Trends" Combo) + 변동성 타깃.

```
종목별 신호 frac = 보유 중인 Donchian 기간 비율, 기간 {5,10,20,30,60,90,150,250,360}일
  진입: 종가 = n일 최고 종가 / 손절선: 중앙값 래칫(내려가지 않음) / 청산: 종가 < 손절선
BTC 슬리브 비중   = 0.5 × frac × min(0.40/σ90, 1)
알트 슬롯 비중    = 0.05 × frac × min(0.60/σ90, 1)   (월말 유니버스 상위 10, 1/10씩)
유니버스: 상장 365일↑, 30일 중위 거래대금 $2M↑, 스테이블/레버리지/래핑 제외, 거래대금 순
리밸런스: 추세 신호 변화 즉시 / 변동성 변화는 슬롯 대비 20% 넘을 때만
```

**생존편향 없는 백테스트** (상장폐지 195개 포함 681개 페어, 편도 비용 0.15%, `scripts/backtest_trend_rotation.py`):

| | 현재(구) cycle_aware | **Trend Rotation** | BTC 보유 |
|---|---|---|---|
| CAGR (2018-09~2026-10) | 21.9% | 22.8% (현금 3% 운용 시 25.6%) | 35.0% |
| Sharpe | 1.06 | **1.14** (1.26) | 0.80 |
| MDD | −28.4% | −28.2% (−24.8%) | −76.6% |
| 설계/검증/홀드아웃 Sharpe | 1.32 / 0.72 / 0.79 | 1.33 / 1.31 / 0.51 | |
| 파라미터 섭동 시 Sharpe 범위 | 0.07 ~ 1.17 | 1.15 ~ 1.27 | |

- 교체 이유는 "수익률이 크게 높아서"가 아니라 **근거와 견고성**: 구 전략의 평균회귀·ADX·반감기 요소는 근거가 약했고 파라미터를 조금만 바꿔도 성과가 무너졌음 (과적합 신호)
- 부트스트랩: Trend Rotation 이 더 나을 확률 76% (95% 유의 아님). 8년 데이터로는 어떤 전략도 확정 불가
- 구조적 한계: 강세장에선 BTC 보유보다 덜 벎 (평균 노출 ~26%). 폭락장 방어가 대가
- 근거 문헌·교차검증 내역: `tasks/lessons.md` L12~L15

## 📚 과거 기록 — 5년 multi-regime 검증 (Phase 3)

BTC 5년(2021-05 ~ 2026-05)을 3등분해 LUNA/FTX 폭락, 반감기 상승, 횡보장을 각각 평가.

| 전략 | 5년 수익률 | Sharpe | MDD | 3 regime 양수 Sharpe |
|---|---|---|---|---|
| Donchian-ATR | +470% | 0.61 | −60% | 3/3 |
| TSMOM | +107% | 0.64 | −44% | 2/3 |
| MA cross | +129% | 0.57 | −64% | 2/3 |
| **🏆 CRSI** | **+63%** | **0.61** | **−23%** | **3/3** ⭐ |
| Larry-ATR | +74% | 0.47 | −51% | 1/3 |
| Ensemble | +9% | 0.18 | −48% | 1/3 |
| RSI | −4% | 0.17 | −66% | 2/3 |
| 변동성 돌파 | −76% | −0.41 | −82% | 1/3 |

**Connors RSI(CRSI)가 진정한 robust 챔피언**:
- 폭락장(B&H −52%)에서 **유일하게 양수 수익 +9.82%**, MDD −8.59%
- 모든 regime에서 **Sharpe > 0.5**, MDD < 11%
- "절대 수익률"보다 "위험조정 + 자본 보전"에서 압도적

## 설치 & 실행

```powershell
# (권장) 가상환경
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 의존성
pip install -r requirements.txt

# Streamlit 대시보드 실행
streamlit run src/ui/app.py
```

브라우저에서 좌측 사이드바로 코인/기간 설정 후 탭 3개에서 운영:
- 📈 **단일 백테스트**: 전략 선택 + 파라미터 슬라이더 + 가격/매매시점/자산곡선
- 🔎 **파라미터 최적화**: 그리드 서치 + 2D 히트맵
- 🌐 **멀티 코인 비교**: 여러 코인에 같은 전략을 동시 적용

## 프로젝트 구조

```
.
├── README.md
├── smoke_test.py               빠른 동작 확인 (등록된 전체 전략)
├── requirements.txt
├── .env.example                실거래 시 API 키 (백테스트는 불필요)
├── .gitignore
│
├── config/
│   └── config.yaml             기본 파라미터 (Walk-forward 결과 반영)
├── data/                       OHLCV 캐시 (gitignore)
│
├── scripts/                    분석/검증 스크립트
│   ├── validate_5y.py          5년 multi-regime walk-forward 검증
│   └── grid_search.py          그리드 서치 + 50/50 walk-forward
│
├── src/
│   ├── data/binance_data.py    Binance OHLCV fetcher + 캐시 백필
│   ├── strategies/             전략 모듈 (REGISTRY로 일괄 관리)
│   │   ├── base.py             Strategy 추상 클래스
│   │   ├── volatility_breakout.py    Larry Williams 원안
│   │   ├── ma_cross.py         이동평균 크로스
│   │   ├── rsi.py              RSI 평균회귀
│   │   ├── crsi.py             ⭐ Connors RSI (챔피언)
│   │   ├── donchian_atr.py     Donchian 돌파 + ATR Chandelier (Turtle 현대화)
│   │   ├── tsmom.py            Vol-Targeted Time-Series Momentum
│   │   ├── larry_atr.py        Larry 돌파 + ATR Trailing + Vol Sizing
│   │   └── ensemble.py         가중 앙상블 (분산 효과)
│   ├── backtest/
│   │   ├── engine.py           수수료/슬리피지 반영 엔진 (lookahead 방지)
│   │   ├── metrics.py          수익률 / CAGR / MDD / Sharpe / 승률
│   │   ├── optimizer.py        그리드 서치
│   │   └── multi_coin.py       멀티 코인 배치 백테스트
│   ├── utils/
│   │   └── indicators.py       공용 지표 (ATR / Wilder RSI / RealizedVol)
│   └── ui/app.py               Streamlit 대시보드 (3-탭)
│
└── tasks/
    ├── todo.md                 작업 계획
    └── lessons.md              핵심 교훈 (시행착오 기록)
```

## 빠른 검증

```powershell
# 등록된 전략 동작 확인 (BTC 1년 데이터로 빠르게)
python -X utf8 smoke_test.py

# 5년 multi-regime 결정타 검증 (시간 ~3분)
python -X utf8 scripts/validate_5y.py

# 그리드 서치 + walk-forward (시간 ~5분)
python -X utf8 scripts/grid_search.py
```

> 콘솔 한글이 깨질 경우 `python -X utf8`로 실행.

## 등록된 전략 (10개)

| 이름 | 분류 | 특징 |
|---|---|---|
| `donchian_ensemble` 🏆 | 추세 앙상블 | 9개 기간 Donchian + 중앙값 래칫 손절 + 변동성 타깃 (라이브 Trend Rotation 의 종목별 신호) |
| `volatility_breakout` | 단기 추세 | Larry Williams 원안 (K값 돌파) |
| `ma_cross` | 추세 | 단기/장기 이동평균 크로스 |
| `rsi` | 평균회귀 | RSI 단순 크로스 |
| `crsi` ⭐ | 평균회귀 | Connors RSI 3-요소 합성 + 추세 필터 |
| `donchian_atr` | 추세 추종 | N일 신고가 돌파 + ATR Chandelier trailing |
| `tsmom` | 추세 + 사이징 | Vol-targeted Time-Series Momentum |
| `larry_atr` | 하이브리드 | 변동성 돌파 + ATR Trailing + Vol Sizing |
| `ensemble` | 결합 | 7개 전략 가중 평균 + soft threshold |
| `cycle_aware` | 적응 | ADX regime + SMA200 필터 + BTC 반감기 사이클 + Vol-targeting (2026-10 까지 라이브, 과적합 판정으로 교체) |

## 새 전략 추가 방법

1. `src/strategies/<my_strategy>.py` 생성, `Strategy` 상속, `generate_signals(ohlcv) -> Series` 구현
2. `src/strategies/__init__.py`의 `REGISTRY` dict에 `StrategyMeta(cls, label, params=(ParamSpec, ...))` 등록
3. 끝 — UI 슬라이더는 ParamSpec에서 자동 생성됨

신호 규칙:
- 인덱스는 OHLCV와 동일, 값은 `[0, 1]` (또는 max_leverage 까지 확장)
- **lookahead 금지**: i 시점 신호는 i 시점 정보까지만 사용. 엔진이 자동으로 `signal.shift(1)` 적용

## 안전 원칙

- API 키는 `.env`에 (코드/git 커밋 금지, `.gitignore` 포함)
- 백테스트에 수수료(0.1%) + 슬리피지(0.05%) 반영
- 실거래 전 반드시 Testnet으로 갭(데이터 지연 / 슬리피지 / 거래소 규칙) 검증
- 그리드 서치 결과는 항상 walk-forward로 over-fit 확인

## Phase 4 — Binance Testnet 실 매매 (가짜 돈, 진짜 API)

매일 한 번씩 Trend Rotation 목표 비중으로 **실제 Binance Testnet API**에 주문 → 결과를
state.json + HTML 대시보드 + Telegram 알림으로 저장. 거래소 규칙(LOT_SIZE,
MIN_NOTIONAL, 정밀도), 부분 체결, 주문 거부 같은 실전 버그를 0원 리스크로 검증.

### 핵심 동작

- **신호 시점**: 어제 UTC 00:00 마감 봉 → 종목별 Donchian 앙상블 → 목표 비중 → 시장가 주문
- **유니버스**: 월말에 메인넷 공개 데이터로 재선정. testnet 에서 거래 불가한 종목은 건너뜀
- **주문 순서**: 매도 먼저 → USDT 확보 후 매수. $5 미만 주문은 생략
- **잔고 추적**: Binance 계정이 source-of-truth (매 tick 잔고 재조회)
- **외부 입출금 분리**: tick 사이 설명 안 되는 자산 변화(testnet 잔고 리셋 등)는 성과(NAV)에서 제외
- **재실행 안전**: 같은 봉(`last_bar_time`)을 두 번 처리해도 거래 중복 없음
- **소액 계좌**: 총자산 < $3,000 이면 알트 슬리브 끄고 BTC 단독 (최소 주문금액 대응)
- **테스트 게이트**: 워크플로우가 `pytest` 를 먼저 돌리고 실패하면 매매하지 않음

### 구조

```
src/strategies/donchian_ensemble.py  Donchian 앙상블 신호 (백테스트·라이브 공용)
src/portfolio/
├── universe.py       유니버스 선정 / 월중 제외 규칙
└── allocator.py      목표 비중 + 리밸런스 밴드 (백테스트·라이브 공용)

src/live/
├── client.py             testnet/mainnet 토글 Binance Client
├── executor.py           LOT_SIZE/MIN_NOTIONAL 헬퍼, 체결 정규화
├── portfolio_executor.py 멀티코인 리밸런스 (매도→매수)
└── portfolio_tick.py     잔고→유니버스→신호→안전장치→주문→state/dashboard

src/common/           live tick이 쓰는 공유 유틸
├── state.py          JSON 영속화 (data/live_state.json)
└── dashboard.py      state → HTML (NAV vs BTC 보유)

src/notifier/telegram.py  매 tick 한국어 메시지 (리밸런스 / 정지 / 오류 / 보유 비중)

scripts/live_tick.py                엔트리 포인트
scripts/backtest_trend_rotation.py  생존편향 없는 백테스트 (라이브와 같은 함수)
scripts/fetch_all_pairs.py          상장폐지 포함 전체 USDT 페어 일봉 → data/all/
tests/test_trend_rotation.py        단위 + 가짜 거래소 통합 테스트
.github/workflows/live_trading.yml 매일 UTC 00:35 (KST 09:35) self-hosted runner
docs/live_dashboard.html          생성된 대시보드 (TESTNET 뱃지 초록)
data/live_state.json              현재 상태 (자동 커밋됨)
```

### Testnet 가입 + 키 발급 (~3분)

1. https://testnet.binance.vision 접속
2. GitHub 계정으로 로그인
3. "Generate HMAC_SHA256 Key" 클릭 → **API Key + Secret Key 안전한 곳에 복사**
4. 가입과 동시에 가짜 USDT ~10000 + 가짜 BTC 등이 자동 지급됨

### GitHub Secrets 등록

1. https://github.com/SiyunCoding/invest-coin/settings/secrets/actions 접속
2. **New repository secret** 클릭, 2번 반복:
   - Name: `BINANCE_TESTNET_API_KEY` / Value: 발급받은 API Key
   - Name: `BINANCE_TESTNET_API_SECRET` / Value: 발급받은 Secret Key

### 로컬 테스트 (선택)

```powershell
$env:BINANCE_TESTNET_API_KEY = "복사한 키"
$env:BINANCE_TESTNET_API_SECRET = "복사한 시크릿"
python -X utf8 scripts/live_tick.py
# → 첫 실행에서 testnet 잔고 조회 + 신호 계산 + (필요 시) 매매
```

### 자동 실행 — Oracle Cloud self-hosted runner 필수

⚠️ **Binance는 GitHub Actions hosted runner (US 데이터센터 IP)를 차단** (testnet/mainnet 모두 451 에러).
실거래 자동화는 **한국/아시아 region 서버에 self-hosted runner**가 필수.

**권장 인프라: Oracle Cloud Always Free**
- 평생 무료, `ap-chuncheon-1` (춘천) region에서 한국 IP 사용 가능
- Shape: `VM.Standard.E2.1.Micro` (AMD x86, Ubuntu 22.04)
- 또는 ARM `VM.Standard.A1.Flex` (1 OCPU + 6GB RAM 무료 한도)

**설정 순서**:

1. Oracle Cloud 가입 → 인스턴스 생성 → Public IP 할당 → SSH 접속
2. 서버에 Python 3.11 설치:
   ```bash
   sudo apt update -qq && \
   sudo apt install -y -qq software-properties-common curl git && \
   sudo add-apt-repository -y ppa:deadsnakes/ppa && \
   sudo apt install -y -qq python3.11 python3.11-venv python3.11-distutils && \
   curl -sS https://bootstrap.pypa.io/get-pip.py | sudo python3.11
   ```
3. GHA self-hosted runner 등록 (token은 repo Settings → Actions → Runners):
   ```bash
   mkdir -p ~/actions-runner && cd ~/actions-runner
   curl -L -o actions-runner.tar.gz "https://github.com/actions/runner/releases/download/v<latest>/actions-runner-linux-x64-<latest>.tar.gz"
   tar xzf actions-runner.tar.gz
   sudo ./bin/installdependencies.sh
   ./config.sh --url https://github.com/<USER>/<REPO> --token <TOKEN> \
       --name invest-coin-runner --labels self-hosted,linux,x64 --unattended
   sudo ./svc.sh install ubuntu && sudo ./svc.sh start
   ```
4. 워크플로우는 이미 `runs-on: [self-hosted, linux, x64]` 로 설정됨

매일 KST 09:35 자동 실행 → state.json + dashboard.html 자동 commit.
대시보드 우상단 뱃지가 **TESTNET** (초록)으로 표시됨.

### 안전장치 (코드에 이미 포함)

| 보호 | 동작 |
|---|---|
| Symbol filter 자동 적용 | LOT_SIZE step / MIN_NOTIONAL 거래소 규칙 준수, 미달 주문 생략 |
| 잔고 한도 | 매도 먼저 실행 후 남은 USDT 범위에서만 매수 |
| 같은 봉 방어 | `last_bar_time` 비교로 같은 봉 두 번 매매 안 함 |
| 리밸런스 밴드 | 변동성 때문만의 비중 변화는 슬롯 대비 20% 넘을 때만 (회전·비용 절감) |
| 손실 한도 | 직전 tick 대비 −5% 이하면 **매수만** 중지 (청산·축소는 허용) |
| 이상 목표 | NaN/음수/총합>100% 면 주문 중지 |
| 비상정지 | 프로젝트 루트에 `.halt` 파일이 있으면 모든 주문 중지 |
| 주문 거부 처리 | 종목별 `BinanceAPIException` 을 에러 trade로 기록하고 나머지 종목은 계속 |

### Mainnet으로 전환할 때 (Phase 5)

`config/live_trading.yaml` 생성하고:

```yaml
testnet: false   # ⚠️ 실거래 활성화
```

추가 secrets 필요:
- `BINANCE_API_KEY` / `BINANCE_API_SECRET` (실 계정의 API 키, **출금 권한 ❌**, 거래 권한만)

**Mainnet 전환 전 남은 일** (Phase 5):
- IP 화이트리스트: Oracle Cloud 인스턴스의 public IP 고정 후 Binance API key에서 화이트리스트 등록
- 자본 $3,000 미만이면 BTC 단독으로 돈다는 점 확인 (`min_equity_for_alts`)
- (선택) 유휴 USDT → Simple Earn Flexible (현재 APR ~3.3%, testnet 미지원이라 mainnet 에서만 검증 가능, 거래소 리스크 감수)
