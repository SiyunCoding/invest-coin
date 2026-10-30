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
- [x] **H2**: `fetch_ohlcv`에서 미마감 봉 자동 drop (실시간 매매 안전성)
- [x] **H3**: Ensemble threshold soft 매핑 (TSMOM/LarryATR vol-sizing 보존)
- [x] **H4**: `CycleAwareEnsemble.apply_cycle` 플래그 + ParamSpec "bool" 지원 + UI 체크박스
- [x] cycle_aware markup multiplier 비대칭 버그 (target_vol에 적용으로 변경)

## ✅ Phase 4 — Binance Testnet 실 매매 (완료, 운영 중)

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
- [~] cycle_aware 신호가 백테스트와 동일하게 계산됨 (전략 교체로 대체 — Trend Rotation 은 백테스트·라이브 같은 함수)

## ✅ Phase 4.6 — 전략 교체: cycle_aware → Trend Rotation (2026-10-29)

### 조사·검증
- [x] 서브에이전트 조사 2라운드 (추세/평균회귀/국면/반감기/비용/사이징/멀티코인/현금수익/전체 문헌) + 교차검증 2회 (출처 39건, 날조 0, 부분오류 7건 정정)
- [x] cycle_aware 진단: 구성요소 ablation (반감기·ATR 무효), 파라미터 섭동 Sharpe 0.07~1.17 → 과적합 판정
- [x] testnet 성과 왜곡 발견: 잔고 리셋으로 외부 자금 ~$22.8k 유입 → 실제 전략 성과 약 −5% (표면 +26%)
- [x] Combo(Donchian 앙상블) 재현 → 약점 진단 (상승장 참여 부족 / 횡보 손실 / 긴 낙폭 / 유휴 현금)
- [x] 사이징 대안 5종 (장기변동성·조건부·하방·VP·코어) → BTC 단독에선 Sharpe 개선 없음 (수익↔낙폭 교환일 뿐)
- [x] 상장폐지 195개 포함 681개 페어 수집, 액면변경/심볼 재사용 9건 정제 → 생존편향 제거 (15코인 Sharpe 1.35 → 실제 1.05)
- [x] BTC 50% + 알트 상위10 50% 확정: 섭동 Sharpe 1.15~1.27, 비용 스트레스 통과, 튜닝 후 OOS +5.1% (구 −5.6%)

### 구현
- [x] src/strategies/donchian_ensemble.py, src/portfolio/ (universe, allocator)
- [x] src/live/portfolio_executor.py (매도→매수, 최소주문 생략), portfolio_tick.py (외부 입출금 분리 NAV, 손실 한도는 매수만 차단)
- [x] 대시보드/텔레그램 멀티코인화, 구 tick.py 제거
- [x] scripts/backtest_trend_rotation.py — 라이브와 같은 함수로 재현 (scratch 결과와 일치)
- [x] tests/ 24개 + 워크플로우 테스트 게이트

### 남은 일
- [ ] testnet 2~4주 운영: 월말 유니버스 교체 1회 이상, 매도→매수 순서, testnet 미지원 종목 처리 확인
- [x] 선물 스캘퍼 중단 (2026-10-29 서버에서 stop + disable 확인. 최종 demo 성과 +$65 / 진입 13회, 6월 초 이후 사실상 미동작)
- [x] PR #1 머지 + testnet 첫 tick 검증 (2026-10-29: 10종목 유니버스, 매도 1 → 매수 6, 목표 비중 일치)
- [x] 운영 감시: 워크플로우 실패 시 Telegram 경보, watchdog (30시간 tick 없으면 경보)
- [x] 비상정지 버그 수정: 러너 checkout 의 git clean 이 .halt 를 지워 작동 안 하던 문제 → ~/.invest-coin.halt 도 확인
- [ ] mainnet 전 자본 규모 결정 ($3,000 미만이면 BTC 단독 운용) → config/live_trading.example.yaml 참고
- [ ] (선택) mainnet 에서 유휴 USDT Simple Earn 연동 검토 (APR ~3.3%, 백테스트 Sharpe 1.14 → 1.26)

## ✅ Phase 4.7 — 품질·보안 정비 (2026-10-30)

- [x] 리뷰 4종 (실매매 정확성 / 보안 / 품질·구조 / 백테스트·데이터) 서브에이전트 + 수정 후 diff 교차검증
- [x] 실매매: 주문 오류 시 state 커밋 누락(기록 소실·고아 포지션) 수정, 소액 수량 지수표기 거부 수정,
      정지/미체결 시 진입 누락 수정, 월말 tick 누락 시 재선정 지연 수정, NAV 수수료 반영, 끊긴 데이터 종목 제외,
      주문 후 단계 실패 시 state 저장+재동기화, 네트워크 재시도, 먼지 정리, 소액 경계 히스테리시스
- [x] 보안: 워크플로우 쓰기 토큰 최소화, mainnet 키는 mainnet 모드에서만 전달, action SHA 고정, 의존성 버전 고정 +
      매 실행 새 venv, 동시 실행 방지, 텔레그램 토큰 로그 마스킹, 대시보드 XSS/SRI, .gitignore 강화, Dependabot
- [x] 정리: 선물 스캘퍼 코드·튜닝 스크립트 삭제, 연구 스크립트 research/ 이동, 신호 함수를 src/portfolio/signals.py 로
      분리(라이브가 연구 전략 REGISTRY 에 의존하지 않음), executor 통합, 중복 제거, 미사용 의존성 제거
- [x] 백테스트: 거래 추출 한 봉 밀림, 최적화 MDD 정렬 반대, 짧은 기간 CAGR 폭주, 공백일 수익 누락 수정
- [x] 테스트 25 → 47개, README 재작성
- [ ] **(소유자)** README 보안 체크리스트: 저장소 Private 전환, Actions 설정, mainnet 키 정리

## 🔮 Phase 5 — 실거래 (Phase 4 통과 후)
- [ ] Binance API 키 인증 + 테스트넷 우선
- [x] 손실 한도 (직전 tick 대비 −5% → 매수 중지, 2026-10 버그 수정: 이전엔 하루 1 tick 이라 절대 발동 안 했음)
- [x] 포지션 크기 한도 (BTC 슬리브 50% + 알트 슬롯 5%씩, 총 100% 상한)
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
