# Invest Coin — 작업 계획

## ✅ Phase 1 — 백테스팅 기반 (완료)
- [x] requirements.txt / .gitignore / .env.example
- [x] config/config.yaml
- [x] src/data/binance_data.py (OHLCV 수집 + 캐시)
- [x] src/strategies/base.py (Strategy ABC)
- [x] src/strategies/volatility_breakout.py
- [x] src/backtest/engine.py (수수료/슬리피지 반영, lookahead 방지)
- [x] src/backtest/metrics.py (수익률 / CAGR / MDD / Sharpe / 승률)
- [x] src/ui/app.py (Streamlit 대시보드)

## ✅ Phase 2 — 전략 확장 (완료)
- [x] MA cross / RSI 전략
- [x] StrategyMeta + ParamSpec 등록 시스템 (UI 자동 생성)
- [x] 그리드 서치 (src/backtest/optimizer.py)
- [x] 멀티 코인 배치 (src/backtest/multi_coin.py)
- [x] Streamlit 3-탭 (단일 / 최적화 / 멀티코인)

## ✅ Phase 3 — 신규 전략 + Multi-regime 검증 (완료)
- [x] 서브에이전트 3개로 최신 전략 조사 (모멘텀 / 평균회귀 / 하이브리드)
- [x] CRSI (Connors RSI) 구현 — 평균회귀 1순위
- [x] Donchian-ATR (Turtle 현대화) 구현 — 추세 1순위
- [x] Vol-Targeted TSMOM 구현
- [x] Larry-ATR (변동성 돌파 + ATR Trail + Vol Sizing) 구현
- [x] WeightedEnsemble (7개 결합) 구현
- [x] src/utils/indicators.py (ATR/Wilder RSI/RealizedVol) 공용 모듈
- [x] load_ohlcv 캐시 백필 버그 수정
- [x] CRSI 디폴트 walk-forward 검증값으로 업데이트 (lower 5→20, trend 100→150)
- [x] 5년 multi-regime 검증 → **CRSI가 robust 챔피언 확정**

### Phase 3 검증 결과 (BTC 5년 / 3 regime)
| 전략 | min Sharpe | min 수익률 | max MDD | + regimes |
|---|---|---|---|---|
| **CRSI** | **+0.56** | **+8.69%** | **−10.85%** | **3/3** ⭐ |
| Donchian-ATR | +0.16 | −0.31% | −52.00% | 3/3 |

> CRSI만 LUNA/FTX 폭락장(B&H −52%)에서도 양수 수익(+10%) + MDD < 11%

## ✅ Phase 3.5 — 코드 정리 (완료)
- [x] 분석 스크립트 정리 (scripts/ 디렉토리)
- [x] 임시/시행착오 스크립트 삭제 (compare_*.py 등)
- [x] smoke_test.py 8개 전략 검증으로 업데이트
- [x] rsi.py 별칭 제거
- [x] README.md 5년 결과 반영
- [x] tasks/lessons.md 작성

## ✅ Phase 3.6 — 코드 감사 + High-severity 버그 수정 (완료)
- [x] **H1**: 캐시 신선도 — 마지막 마감 봉 기준 비교 (불필요한 API 호출 제거)
- [x] **H2**: `fetch_ohlcv`에서 미마감 봉 자동 drop (페이퍼 트레이딩 안전성)
- [x] **H3**: Ensemble threshold soft 매핑 (TSMOM/LarryATR vol-sizing 보존)
- [x] **H4**: `CycleAwareEnsemble.apply_cycle` 플래그 + ParamSpec "bool" 지원 + UI 체크박스
- [x] cycle_aware markup multiplier 비대칭 버그 (target_vol에 적용으로 변경)

## ✅ Phase 4 — 페이퍼 트레이딩 (완료, 운영 중)

### 구축한 것
- [x] src/paper/portfolio.py — 가상 포트폴리오 + 리밸런싱 (연속 포지션, 수수료/슬리피지)
- [x] src/paper/state.py — JSON 영속화 (data/paper_state.json)
- [x] src/paper/tick.py — fetch→signal→rebalance→save→render 한 사이클
- [x] src/paper/dashboard.py — state → HTML (다크 테마, Chart.js)
- [x] scripts/paper_tick.py — 엔트리 포인트 (로컬/GHA 공용)
- [x] .github/workflows/paper_trading.yml — 매일 UTC 00:30 cron
- [x] 같은 봉 재처리 방어 (last_bar_time 비교)
- [x] 자산 1% 미만 변동은 리밸런싱 스킵 (하이스테리시스)

### 운영 원칙
1. 전략 = **cycle_aware** (BTC 5년 검증 챔피언, Sharpe 0.76, min Sharpe 0.94)
2. 초기 가상자본 $100,000
3. 매일 UTC 00:30 자동 실행 (어제 마감 봉 기준 신호)
4. 거래 발생 시 자동 commit + GitHub Pages로 즉시 확인 가능
5. 최소 1~2주 운영 후 페이퍼 vs 백테스트 일치성 확인

### 성공 기준 (Phase 5 진입 조건)
- [ ] 7일 연속 자동 실행 무중단
- [ ] cycle_aware 신호가 매일 일관성 있게 계산됨
- [ ] 신호 변경 시 거래 실제 체결 (signal 0→0.5 같은 케이스)
- [ ] MDD가 백테스트 평균 범위 내 (cycle_aware: −15% 이내 기대)
- [ ] state.json + dashboard.html 자동 commit 정상

## ✅ Phase 4.5 — Binance Testnet 실 매매 (완료, 운영 중)

### 구축한 것
- [x] src/live/client.py — testnet/mainnet 토글 Binance Client 팩토리
- [x] src/live/executor.py — rebalance_to_target + LOT_SIZE/MIN_NOTIONAL/PRICE_FILTER 자동 적용
- [x] src/live/tick.py — fetch→signal→실 API 주문→state/dashboard
- [x] scripts/live_tick.py — 엔트리 포인트
- [x] .github/workflows/live_trading.yml — KST 09:35 자동 cron (self-hosted runner)
- [x] dashboard mode badge (TESTNET 초록 / mainnet 빨강)

### 인프라 (Oracle Cloud Always Free)
- [x] Oracle Cloud 가입 + 카드 verification (siyunking)
- [x] Always Free 인스턴스 (Ubuntu 22.04, AMD E2.1.Micro, ap-chuncheon-1)
- [x] Ephemeral public IP 할당 (168.107.43.97)
- [x] SSH 키 생성 + 접속 검증
- [x] Python 3.11 + deadsnakes PPA 설치
- [x] GHA self-hosted runner 설치 + systemd 서비스 등록
- [x] Workflow `runs-on: [self-hosted, linux, x64]` 전환

### 첫 거래 검증 (2026-05-17 17:45 UTC)
- Binance Testnet 가입 시 받은 초기 자산 (1 BTC + ~$10k USDT)
- cycle_aware 신호 = 0.0 (BTC 보유 0% 목표)
- → 1.0 BTC 시장가 매도 @ $78,041 (FILLED)
- → 최종: $88,041 USDT + 0 BTC
- **실 Binance API 인증 + 주문 + 체결 + 응답 파싱 모두 검증 완료**

### Phase 5 진입 조건 (1~2주 운영 후 평가)
- [ ] 7일 연속 무중단 자동 실행
- [ ] 신호 변경 시 (0 → 양수) 매수 거래 발생 검증
- [ ] state.json + dashboard.html 매일 자동 commit 정상
- [ ] cycle_aware 신호가 백테스트와 동일하게 계산됨

## 🔮 Phase 5 — 실거래 (Phase 4 통과 후)
- [ ] Binance API 키 인증 + 테스트넷 우선
- [ ] 일일 손실 한도 (예: 자본의 −5%에서 자동 정지)
- [ ] 포지션 크기 한도 (예: 코인당 최대 자본 50%)
- [ ] kill switch (이상 신호 감지 시 즉시 청산 + 정지)
- [ ] 슬리피지 보호 (limit order, 체결 실패 시 재시도)
- [ ] 거래소 장애 대응 (재시도, 백오프)

## 📝 리뷰

### Phase 1-3 성과
- 백테스팅 시스템 구축 + 8개 전략 + 5년 multi-regime 검증 완료
- **CRSI를 robust 챔피언으로 확정** — 폭락장에서도 양수 수익 가능한 유일한 전략
- 단순 그리드 서치의 over-fit 위험을 walk-forward로 직접 확인
- Streamlit 대시보드로 누구나 슬라이더 조정해 실험 가능

### 핵심 lessons (tasks/lessons.md 참조)
- 짧은 기간 백테스트는 환경 편향 위험
- "최고 수익률" 추구 = over-fit, "꾸준한 수익률" = robust
- 앙상블은 만능 아님 — 약한 컴포넌트가 발목 잡음
- 단순한 전략 + 적은 신호가 OOS에서 잘 살아남음
