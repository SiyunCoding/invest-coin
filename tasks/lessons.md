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
