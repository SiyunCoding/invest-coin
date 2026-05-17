# Invest Coin — 바이낸스 자동거래 시스템

Python + Streamlit 기반 암호화폐 자동거래.
**1단계 백테스팅 → 2단계 모의투자 → 3단계 실거래** 순으로 단계적 확장.

## 현재 진행 단계

- ✅ **Phase 1** 백테스팅 시스템 + Streamlit 대시보드 + 변동성 돌파 전략
- ✅ **Phase 2** 전략 확장 (MA cross / RSI), 그리드 서치, 멀티 코인 비교
- ✅ **Phase 3** 신규 전략 (CRSI / Donchian-ATR / TSMOM / Larry-ATR / 앙상블 / Cycle-Aware) + 5년 multi-regime 검증
- ✅ **Phase 4** Binance Testnet 실 매매 (Oracle Cloud self-hosted runner, 매일 자동 cron, Telegram 알림)
- 🔮 **Phase 5** 실거래 (Testnet 통과 + 안전장치 추가 후)

## 🏆 핵심 발견 — 5년 multi-regime 검증

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
├── smoke_test.py               빠른 동작 확인 (8개 전략)
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
# 8개 전략 동작 확인 (BTC 1년 데이터로 빠르게)
python -X utf8 smoke_test.py

# 5년 multi-regime 결정타 검증 (시간 ~3분)
python -X utf8 scripts/validate_5y.py

# 그리드 서치 + walk-forward (시간 ~5분)
python -X utf8 scripts/grid_search.py
```

> 콘솔 한글이 깨질 경우 `python -X utf8`로 실행.

## 등록된 전략 (9개)

| 이름 | 분류 | 특징 |
|---|---|---|
| `volatility_breakout` | 단기 추세 | Larry Williams 원안 (K값 돌파) |
| `ma_cross` | 추세 | 단기/장기 이동평균 크로스 |
| `rsi` | 평균회귀 | RSI 단순 크로스 |
| `crsi` ⭐ | 평균회귀 | Connors RSI 3-요소 합성 + 추세 필터 |
| `donchian_atr` | 추세 추종 | N일 신고가 돌파 + ATR Chandelier trailing |
| `tsmom` | 추세 + 사이징 | Vol-targeted Time-Series Momentum |
| `larry_atr` | 하이브리드 | 변동성 돌파 + ATR Trailing + Vol Sizing |
| `ensemble` | 결합 | 7개 전략 가중 평균 + soft threshold |
| `cycle_aware` 🏆 | 적응 | ADX regime + SMA200 필터 + BTC 반감기 사이클 + Vol-targeting (Phase 4 디폴트) |

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
- 실거래 전 반드시 페이퍼 트레이딩으로 갭(데이터 지연 / 슬리피지) 검증
- 그리드 서치 결과는 항상 walk-forward로 over-fit 확인

## Phase 4 — Binance Testnet 실 매매 (가짜 돈, 진짜 API)

매일 한 번씩 cycle_aware 신호로 **실제 Binance Testnet API**에 주문 → 결과를
state.json + HTML 대시보드 + Telegram 알림으로 저장. 거래소 규칙(LOT_SIZE,
MIN_NOTIONAL, 정밀도), 부분 체결, 주문 거부 같은 실전 버그를 0원 리스크로 검증.

### 핵심 동작

- **신호 시점**: 어제 UTC 00:00 마감 봉 → cycle_aware 신호 계산 → 즉시 시장가 주문
- **거래 단위**: 연속 포지션. 신호 0.6이면 자산의 60%를 BTC로 보유
- **잔고 추적**: Binance 계정이 source-of-truth (매 tick 잔고 재조회)
- **하이스테리시스**: 자산의 1% 미만 변동은 리밸런싱 스킵 (수수료만 까임)
- **재실행 안전**: 같은 봉(`last_bar_time`)을 두 번 처리해도 거래 중복 없음

### 구조

```
src/live/
├── client.py         testnet/mainnet 토글 Binance Client
├── executor.py       rebalance + LOT_SIZE/MIN_NOTIONAL/PRICE_FILTER 자동 적용
└── tick.py           fetch→signal→Binance 주문→state/dashboard

src/common/           live tick이 쓰는 공유 유틸
├── state.py          JSON 영속화 (data/live_state.json)
└── dashboard.py      state → HTML

src/notifier/         Telegram 알림
└── telegram.py       매 tick 결과 한국어 메시지 (변함없음 / 매수·매도 체결 / 오류)

scripts/live_tick.py              엔트리 포인트
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
| Symbol filter 자동 적용 | LOT_SIZE step / MIN_NOTIONAL / PRICE_FILTER 거래소 규칙 준수 |
| 잔고 한도 | 사려는 금액이 USDT 잔고 초과 시 가능한 만큼만 매수 |
| 수량 한도 | 팔려는 양이 BTC 잔고 초과 시 잔고까지만 매도 |
| 같은 봉 방어 | `last_bar_time` 비교로 같은 봉 두 번 매매 안 함 |
| 1% 미만 리밸 스킵 | 자산의 1% 미만 변동은 수수료 까임 방지 위해 무시 |
| 주문 거부 처리 | `BinanceAPIException` 잡아서 에러 trade로 기록 (다음 tick에 재시도) |

### Mainnet으로 전환할 때 (Phase 5)

`config/live_trading.yaml` 생성하고:

```yaml
testnet: false   # ⚠️ 실거래 활성화
```

추가 secrets 필요:
- `BINANCE_API_KEY` / `BINANCE_API_SECRET` (실 계정의 API 키, **출금 권한 ❌**, 거래 권한만)

**Mainnet 전환 전 추가 안전장치 필요** (Phase 5에서 구현):
- 일일 손실 한도 (예: -5% 도달 시 자동 정지)
- 포지션 최대 캡 (예: 자본의 50%까지만)
- 텔레그램 즉시 알림
- IP 화이트리스트: Oracle Cloud 인스턴스의 public IP 고정 후 Binance API key에서 화이트리스트 등록
