# Lessons — 시행착오 기록

CLAUDE.md 원칙에 따라 같은 실수를 두 번 안 하기 위한 노트.
각 lesson은 "발생한 상황 + 원인 + 다음에 어떻게 할지"로 기록.

---

## L1. 짧은 기간 백테스트의 환경 편향

**상황**
1년치(2025-05~2026-05) 데이터로 5개 전략을 비교했더니 CRSI가 압도(+4%), Donchian-ATR이 꼴찌(−33%).
3년치로 확장하니 Donchian-ATR이 1등(+192%), CRSI는 평범(+6%).
5년치로 확장하니 CRSI가 진짜 robust 챔피언(모든 regime Sharpe>0.5).

**원인**
1년치는 우연히 하락/횡보장만 포함 → 평균회귀 전략에 유리한 편향.
**시장 환경 한 가지(상승/하락/횡보) 1회만 본 결과는 신뢰할 수 없음**.

**다음에 어떻게**
- 의미 있는 백테스트는 최소 **3년 이상 + multi-regime** (상승/하락/횡보 다 포함).
- 같은 전략을 여러 기간 buckets로 쪼개서 robust 점수 산출 (min Sharpe / max MDD).
- 1년 데이터로 "이 전략이 우수하다"라는 결론을 절대 말하지 않기.

---

## L2. 그리드 서치 = over-fit 함정

**상황**
3년 BTC에서 RSI 그리드 서치 → period=28, oversold=25, overbought=80이 "최적" (1 trade, +200% 수익).
Walk-forward (50/50 split)로 보니 OOS에서 거래 0건, 수익 0%. **그냥 운빨이었음**.
Donchian-ATR lookback=80도 IS Sharpe 1.79 → OOS Sharpe −1.02 (붕괴).

**원인**
한 시장 환경에 fit한 파라미터는 다른 환경에서 무용지물.
"최고 수익률" 한 점을 찾는 그리드 서치 = 노이즈 fit.

**다음에 어떻게**
- 그리드 서치 결과는 **반드시 walk-forward**로 검증 (in-sample 절반 + out-of-sample 절반).
- "최고"가 아니라 **"IS→OOS decay가 작은"** 파라미터를 선택.
- 디폴트 파라미터를 그리드 서치 결과로 무작정 바꾸지 말기. walk-forward robust한 것만 반영.

---

## L3. 캐시 백필 버그 (cache가 옛날 데이터 안 받아옴)

**상황**
3년치(`lookback_days=1095`) 요청했는데 캐시된 1년치만 반환됐음.
B&H 수치가 의심스러워서 발견.

**원인**
`load_ohlcv`가 캐시 존재 시 "최신 부분만 보강"하고 옛날 부분은 보강 안 함.
캐시 `[2025-05 ~ 2026-05]` + 요청 `[2023-05 ~ 2026-05]` → `start_ts >= 2023-05`로 잘라서 반환하지만 실제로는 1년치만 있음.

**다음에 어떻게**
- 캐시 로직: 시작점/끝점 둘 다 비교해서 양방향 보강 (이미 수정 완료).
- 의심스러운 결과 발견 시 가장 먼저 **데이터 양과 범위부터 확인** (`df.index.min()/.max()`, `len(df)`).
- B&H 수치가 직관과 어긋나면 무조건 데이터 의심.

---

## L4. 앙상블은 만능이 아니다

**상황**
WeightedEnsemble을 만들어 7개 전략 결합 → IS 매트릭스에서는 빛났지만(thr=0.3에서 +286%) OOS Sharpe −0.16으로 무너짐.
CRSI 단독 OOS Sharpe 1.15를 못 이김.

**원인**
약한 컴포넌트(Donchian-ATR OOS Sharpe −1.02)가 앙상블 가중치에 포함되면 평균에 끌어내림.
threshold가 너무 높으면 신호 상쇄로 진입 안 됨. threshold가 너무 낮으면 약한 신호도 다 받아 noise.

**다음에 어떻게**
- 앙상블 컴포넌트는 **OOS Sharpe 양수**인 전략만 (CRSI / RSI / MA / TSMOM).
- 앙상블 가중치를 IS 기준으로 튜닝하지 말기.
- 단일 전략이 robust하면 굳이 앙상블로 복잡도 늘리지 말기 (CRSI 단독이 답일 수도).

---

## L5. Streamlit 백그라운드 + UTF-8 콘솔

**상황**
PowerShell에서 `set PYTHONIOENCODING=utf-8`은 Bash 도구 안에서 잘 안 먹힘.
`em-dash`(—) 등 비-ASCII 문자가 cp949 인코딩 에러 일으킴.

**다음에 어떻게**
- 스크립트 실행은 `python -X utf8 script.py`로 통일 (콘솔 cp949 무시).
- print 메시지에 em-dash 사용 자제, ASCII 안전 문자만 (` - `, `-->`).
- Streamlit은 `--server.headless=true` 옵션 + 백그라운드로 실행.

---

## L6. dataclass + Strategy 베이스 클래스의 default 충돌

**상황**
초기에 `name: str = "base"`가 `@dataclass class Strategy(ABC)` 베이스에 있으면 서브클래스에서 `name: str = "rsi"` 같은 default 정의 시 dataclass에서 "non-default after default" 에러 가능.
실제로는 서브클래스가 모두 default-only 필드만 가지므로 무사했지만 잠재 위험.

**다음에 어떻게**
- Strategy 베이스에 default 있는 필드는 항상 끝에 두기.
- 서브클래스도 모든 필드에 default 부여 (kwargs only 보장).
- 더 안전: `@dataclass(kw_only=True)` 사용 (Python 3.10+).

---

## L7. "수익률 최대화"보다 "위험조정수익 + 자본 보전"

**상황**
5년 BTC: Donchian-ATR +470% vs CRSI +63%.
숫자만 보면 Donchian-ATR이 압도지만 MDD가 −60% vs CRSI −23%.
폭락장(B&H −52%) 구간: Donchian −0.31% / CRSI +9.82%.

**원인**
"평균 수익률"은 극단값에 휘둘림. 한 번의 큰 폭락으로 모든 누적 수익을 날릴 수 있음.
복리의 본질 = 자본 보전 > 단발 고수익.

**다음에 어떻게**
- 전략 평가는 항상 **(수익률, Sharpe, MDD)** 트리플로.
- "min Sharpe(최악 regime에서도 양수)"가 진짜 robust 지표.
- 실거래로 갈 전략은 "큰 수익"보다 "큰 손실 안 보는" 것 우선.

---

## L8. 단순함이 robustness의 핵심

**상황**
가장 복잡한 Larry-ATR(Vol-targeted + ATR Trail + 변동성 돌파)이 OOS Sharpe −1.15.
가장 단순한 CRSI(3-요소 RSI 합성 + SMA 필터)가 OOS Sharpe +1.15.

**원인**
복잡한 전략 = 파라미터 많음 = over-fit 자유도 높음.
단순한 전략 = 자유도 낮음 = 노이즈 fit 못 함.

**다음에 어떻게**
- 새 전략 도입 시 "기존 단순 전략 대비 무엇이 더 robust한지" 명확히.
- 파라미터 7개짜리 전략 vs 3개짜리 전략이면 일단 3개부터.
- 가장 robust한 전략은 보통 신호 빈도가 낮고 룰이 명확하다.

---

## L9. 디폴트는 사용자 첫인상

**상황**
초기 CRSI 디폴트(`lower=5`, Connors 원안)는 코인에서 신호가 거의 안 떴음.
1년 데이터로 평가하니 거래 0.7건/코인 → "안 도는 전략" 인상.

**원인**
원안은 전통 자산용. 코인은 변동성이 커서 임계값을 완화해야 함.

**다음에 어떻게**
- 외부 전략 가져올 때 **자산군 차이**를 먼저 확인.
- walk-forward로 자산군 별 적정값을 찾고 디폴트 업데이트.
- ParamSpec에 출처/근거를 도움말로 남기기 (`help="코인은 5 권장 (전통자산은 10)"`).

---

## L10. Binance는 데이터센터 IP를 차단함 (testnet도 동일)

**상황**
1. GitHub Actions hosted runner (ubuntu-latest, US 데이터센터)에서 Binance API 호출 → **HTTP 451**.
2. 그래서 testnet API (`testnet.binance.vision`)로 우회했더니 → **여전히 451**.
3. Binance가 도메인 단위가 아니라 **IP 대역 단위**로 차단함을 확인.

**원인**
Binance는 미국 등 규제 지역에 서비스 불가. AWS US, Azure US, GHA ubuntu-latest 등 데이터센터 IP는 testnet/mainnet 구분 없이 일괄 차단.

**다음에 어떻게**
- 데이터(시세)만 필요한 워크플로우는 **CryptoCompare 폴백** 추가 (`src/data/binance_data.py` 참고). HTTP 451 잡아서 자동 전환.
- 매매(API 인증 필요한 호출)는 **한국/아시아 region의 직접 호스트** 필수. GHA hosted runners로는 절대 불가능.
- "testnet은 geo-block 없을 것"이라는 직관은 틀림. 실증 우선.

---

## L11. Oracle Cloud Always Free + self-hosted runner가 코인 봇의 정답

**상황**
- 24/7 매매 자동화 위해 PC 항상 켜두기 어려움.
- 유료 VPS는 월 ~$5라도 매월 부담.
- GHA hosted는 Binance 차단으로 불가능.

**해결책**
Oracle Cloud Always Free tier에 인스턴스 1대 띄우고 GHA self-hosted runner 등록.
- AMD x86 (`VM.Standard.E2.1.Micro`) 또는 ARM (`A1.Flex`) — 둘 다 평생 무료
- Region: ap-chuncheon-1 (춘천, 한국 IP) → Binance 접근 ✅
- workflow `runs-on: [self-hosted, linux, x64]` 한 줄만 수정
- `actions/setup-python` 제거하고 시스템 python3.11 직접 호출 (self-hosted엔 미리 설치 필요)

**다음에 어떻게**
- 코인 봇 다음 프로젝트는 처음부터 Oracle Cloud self-hosted 가정 (GHA hosted 시도해서 시간 낭비 안 함).
- Oracle 계정 가입 시 카드 거부될 수 있음 → 신용카드 또는 트래블월렛 추천.
- 자원 한도 (Always Free) 초과하면 과금 시작이라 주의.


---

## L12. 생존편향은 멀티코인 백테스트를 통째로 속인다

**상황**
"지금 살아있는 주요 15코인"으로 Donchian 앙상블 포트폴리오를 돌리니 Sharpe 1.35, MDD −17.5%.
상장폐지 195개를 포함한 시점별 유니버스(월말 거래대금 상위 10)로 다시 돌리니 Sharpe 1.05.

**원인**
오늘의 생존 종목을 과거에 소급 선택 = 미래 정보. 동일가중 크립토 포트폴리오의 생존편향은 연 62% 수준까지 보고됨
(Ammann, Burdorf, Liebi, Stöckl 2022, 비심사 원고).

**다음에 어떻게**
- 멀티코인 백테스트는 반드시 `scripts/fetch_all_pairs.py` (상장폐지 포함) + 시점별 유니버스로.
- 데이터 정제: 액면변경/심볼 재사용(COCOS, DREP, SUN, QUICK, BNX, LUNA)과 30일 넘는 공백은 별도 종목으로 끊기.

---

## L13. testnet 잔고 리셋이 성과를 부풀린다

**상황**
구 전략 testnet 성과 +26% (2026-06-28~10-28). 실제로는 testnet 잔고 리셋으로 외부 자금 ~$22.8k 가 3번 유입 → 전략 성과는 약 −5%.

**다음에 어떻게**
- 성과는 외부 입출금을 뺀 시간가중 NAV 로만 본다 (portfolio_tick 이 자동 분리).
- "설명 안 되는 자산 변화 = 직전 보유수량 × 가격 변화로 설명 안 되는 차이" 를 먼저 확인.

---

## L14. 과적합 판별은 "파라미터를 흔들어 보기"가 가장 빠르다

**상황**
cycle_aware 는 기본값 Sharpe 1.06 이었지만 파라미터 40개 랜덤 섭동 시 0.07~1.17 (중앙 0.74).
Donchian 앙상블은 같은 시험에서 0.91~1.15. 전체 기간 Sharpe 만 보면 둘이 같았음.

**다음에 어떻게**
- 전략 비교 시 (1) 섭동 분포 (2) 설계/검증/홀드아웃 분리 (3) 블록 부트스트랩 (4) 시도 횟수 반영 DSR 을 같이 본다.
- 8년 크립토 데이터로는 Sharpe 0.2 차이도 통계적으로 확정 못 함 → 근거 문헌 + 견고성으로 결정.

---

## L15. BTC 단독 추세에선 사이징으로 공짜 개선이 없다

**상황**
장기변동성 재보정 / 조건부 / 하방 변동성 / 진입 시 고정 / 코어 보유 5종 모두 노출↑ = 수익↑·MDD↑ 동반, Sharpe 개선 0.
(BTC 는 주식 같은 leverage effect 가 약하거나 반대라 vol targeting 이 Sharpe 를 거의 안 올림 — Harvey et al. 2018 논리)

**다음에 어떻게**
- 위험 1단위당 수익을 늘리는 건 사이징이 아니라 **다른 수익원 추가** (멀티코인 분산, 유휴 현금 이자).
- 상승장 참여 부족은 구조적 대가로 받아들이고 대시보드에 BTC 보유 대비를 항상 표시.

---

## L16. 고레버리지 무손절 스캘핑은 수학적으로 진다

**상황**
선물 스캘퍼: RSI(5m)>80 숏, 50~75x, TP 마진 30%, 손절 없음, CROSS.
손익분기 승률 80~82% (taker 0.05% 왕복 포함) vs 랜덤워크에서 TP 먼저 닿을 확률 67~77%.
단기 반전 엣지는 거래당 ~1.3bp 로 왕복 비용보다 작음 (Kitron & Wengrowicz 2026 arXiv).

**다음에 어떻게**
- 진입 규칙보다 먼저 "TP/손절 거리 + 비용 → 손익분기 승률"을 계산하고, 그걸 넘는 근거가 있을 때만 만든다.


---

## L17. CI 실패 = 상태 소실이 될 수 있다

**상황**
주문 하나가 거부되면 tick 스크립트가 exit 1 → 워크플로우의 state 커밋 단계가 건너뛰어짐 →
다음 실행의 checkout 이 옛 state 로 덮어씀 → 체결 기록 소실, 새로 산 종목이 추적에서 빠져 "고아 포지션" 위험.

**다음에 어떻게**
- 상태를 쓰는 단계는 `if: always()`. 주문 오류는 exit code 가 아니라 알림으로.
- 외부 부작용(주문) 이후 단계는 실패해도 state 를 먼저 저장하고, 다음 실행이 재동기화하게.
- 러너 작업 폴더는 매번 초기화된다는 전제로 캐시/백업/비상정지 파일은 홈 경로에.

---

## L18. float 를 그대로 API 에 넘기지 말 것

**상황**
`str(0.00007)` = `'7e-05'` → Binance quantity 형식 위반으로 거부. 소액 BTC 매도에서 현실적으로 발생.

**다음에 어떻게**
- 수량/금액은 Decimal 로 step 내림 후 `format(d.normalize(), "f")` 고정소수 문자열로 전송.
- 가짜 거래소 테스트에서 지수 표기를 거부하도록 만들어 회귀 방지.
