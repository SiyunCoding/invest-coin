"""전략 레지스트리.

각 전략에 파라미터 스펙(범위/기본값)을 함께 등록해 UI와 optimizer가 같은 메타데이터를 참조한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import Signal, Strategy
from .crsi import ConnorsRSI
from .cycle_aware import CycleAwareEnsemble
from .donchian_atr import DonchianATR
from .ensemble import WeightedEnsemble
from .larry_atr import LarryATR
from .ma_cross import MACross
from .rsi import RSIStrategy
from .tsmom import VolTargetedTSMOM
from .volatility_breakout import VolatilityBreakout


@dataclass(frozen=True)
class ParamSpec:
    """UI 위젯/optimizer가 동일한 스펙을 참조."""
    name: str
    label: str
    kind: str  # "float" | "int" | "bool"
    default: float
    min: float
    max: float
    step: float
    help: str = ""


@dataclass(frozen=True)
class StrategyMeta:
    cls: type[Strategy]
    label: str
    params: tuple[ParamSpec, ...]


REGISTRY: dict[str, StrategyMeta] = {
    "volatility_breakout": StrategyMeta(
        cls=VolatilityBreakout,
        label="변동성 돌파 (Larry Williams)",
        params=(
            ParamSpec("k", "K값", "float", 0.5, 0.1, 1.5, 0.05,
                     "당일 시가 + (전일 고가-저가)*K 를 돌파하면 매수. 보통 0.3~0.7."),
        ),
    ),
    "ma_cross": StrategyMeta(
        cls=MACross,
        label="이동평균 크로스",
        params=(
            ParamSpec("fast", "단기 MA", "int", 20, 3, 60, 1,
                     "단기 이동평균선의 기간(봉 수). 짧을수록 민감."),
            ParamSpec("slow", "장기 MA", "int", 60, 10, 200, 5,
                     "장기 이동평균선의 기간(봉 수). 단기 < 장기 이어야 함."),
        ),
    ),
    "rsi": StrategyMeta(
        cls=RSIStrategy,
        label="RSI 평균회귀",
        params=(
            ParamSpec("period", "RSI 기간", "int", 14, 5, 50, 1,
                     "RSI 계산 기간. 보통 14."),
            ParamSpec("oversold", "과매도 임계값", "float", 30.0, 10.0, 45.0, 1.0,
                     "RSI가 이 값 아래에서 위로 돌파 시 매수."),
            ParamSpec("overbought", "과매수 임계값", "float", 70.0, 55.0, 90.0, 1.0,
                     "RSI가 이 값 위에서 아래로 돌파 시 매도."),
        ),
    ),
    "crsi": StrategyMeta(
        cls=ConnorsRSI,
        label="Connors RSI (단기 평균회귀 합성)",
        params=(
            ParamSpec("rsi_period", "RSI 기간", "int", 3, 2, 14, 1,
                     "단기 RSI 기간. Connors 원안 3."),
            ParamSpec("updown_period", "UpDown RSI 기간", "int", 2, 2, 10, 1,
                     "연속 상승/하락일 수에 대한 RSI 기간. 원안 2."),
            ParamSpec("pct_lookback", "PercentRank 기간", "int", 100, 20, 250, 10,
                     "1일 ROC 백분위 산출 기간."),
            ParamSpec("lower", "매수 임계값", "float", 20.0, 1.0, 30.0, 1.0,
                     "CRSI가 이 값 미만이면 매수. 코인 walk-forward로 20 검증 (원안 5는 신호 부족)."),
            ParamSpec("upper", "매도 임계값", "float", 70.0, 50.0, 95.0, 1.0,
                     "CRSI가 이 값 초과 또는 단기 MA 위로 복귀 시 매도."),
            ParamSpec("trend_period", "추세 필터 SMA", "int", 150, 20, 250, 10,
                     "이 SMA 위일 때만 매수 (하락장 진입 차단). 코인은 150 권장."),
            ParamSpec("exit_period", "단기 청산 SMA", "int", 5, 2, 20, 1,
                     "이 SMA 위로 복귀하면 청산."),
        ),
    ),
    "donchian_atr": StrategyMeta(
        cls=DonchianATR,
        label="Donchian 돌파 + ATR Chandelier (Turtle 현대화)",
        params=(
            ParamSpec("lookback", "Donchian 기간", "int", 20, 5, 120, 5,
                     "N일 신고가 돌파 시 진입. Turtle 원안 20일."),
            ParamSpec("atr_period", "ATR 기간", "int", 14, 5, 30, 1,
                     "Average True Range 계산 기간 (Wilder smoothing)."),
            ParamSpec("atr_mult", "ATR 배수", "float", 3.0, 1.0, 8.0, 0.5,
                     "추적 손절 = 최고가 - 배수×ATR. 클수록 손절 폭 커짐."),
        ),
    ),
    "tsmom": StrategyMeta(
        cls=VolTargetedTSMOM,
        label="Vol-Targeted TSMOM (변동성 타겟팅 모멘텀)",
        params=(
            ParamSpec("lookback", "모멘텀 기간", "int", 60, 7, 180, 7,
                     "과거 N일 누적 수익률 부호로 진입 결정. 코인은 30~90 권장."),
            ParamSpec("vol_window", "변동성 윈도우", "int", 30, 10, 90, 5,
                     "Realized vol 계산용 EWMA 윈도우 (halflife=window/2)."),
            ParamSpec("target_vol", "목표 연환산 변동성", "float", 0.40, 0.10, 1.00, 0.05,
                     "BTC 자체 변동성 50~80% 대비 약 0.5~0.7배 권장 (0.40 등)."),
            ParamSpec("max_leverage", "최대 포지션", "float", 1.0, 0.5, 2.0, 0.1,
                     "현물 백테스트는 1.0. 레버리지 옵션은 2.0까지."),
        ),
    ),
    "larry_atr": StrategyMeta(
        cls=LarryATR,
        label="Larry 변동성 돌파 + ATR Trailing + Vol Sizing",
        params=(
            ParamSpec("k", "K값", "float", 0.5, 0.1, 1.5, 0.05,
                     "당일 시가 + (전일 고가-저가)*K 를 돌파하면 매수."),
            ParamSpec("atr_period", "ATR 기간", "int", 14, 5, 30, 1, "ATR 계산 기간."),
            ParamSpec("atr_mult", "ATR Trail 배수", "float", 3.0, 1.0, 8.0, 0.5,
                     "추적 손절 = 최고가 - 배수×ATR. 클수록 추세 끝까지 보유."),
            ParamSpec("vol_window", "변동성 윈도우", "int", 30, 10, 90, 5,
                     "포지션 사이즈 결정용 realized vol 윈도우."),
            ParamSpec("target_vol", "목표 연환산 변동성", "float", 0.40, 0.10, 1.00, 0.05,
                     "포지션 사이즈 = target_vol / realized_vol (clip)."),
            ParamSpec("max_leverage", "최대 포지션", "float", 1.0, 0.5, 2.0, 0.1,
                     "현물은 1.0."),
        ),
    ),
    "cycle_aware": StrategyMeta(
        cls=CycleAwareEnsemble,
        label="Cycle-Aware Adaptive Ensemble (반감기 + Regime + Vol-Target)",
        params=(
            ParamSpec("apply_cycle", "BTC 반감기 사이클 가중치 사용", "bool", 1.0, 0.0, 1.0, 1.0,
                     "BTC에서만 켜기. ETH/SOL 등 비-BTC 자산이면 끄세요 (반감기 무관)."),
            ParamSpec("adx_lo", "ADX 하한 (MR ↔ Trend 전환 시작)", "float", 20.0, 10.0, 30.0, 1.0,
                     "ADX 이 값 이하면 100% 평균회귀(CRSI). 20~25에서 soft 전환."),
            ParamSpec("adx_hi", "ADX 상한 (Trend 100%)", "float", 25.0, 20.0, 40.0, 1.0,
                     "ADX 이 값 이상이면 100% 추세(Donchian-ATR)."),
            ParamSpec("sma_period", "추세 필터 SMA", "int", 200, 50, 250, 10,
                     "이 SMA 아래면 강제 평균회귀 모드 (추세 가중치 0)."),
            ParamSpec("target_vol", "목표 연환산 변동성", "float", 0.40, 0.10, 1.00, 0.05,
                     "Vol-targeting 목표값. 코인은 0.30~0.50."),
            ParamSpec("max_leverage", "최대 포지션", "float", 1.0, 0.5, 2.0, 0.1,
                     "현물은 1.0."),
            ParamSpec("mult_markup", "Markup multiplier (반감기+6~+18m)", "float", 1.2, 0.5, 2.0, 0.05,
                     "강세장 phase 사이즈 부스터. 1.2 = 20% 추가 노출."),
            ParamSpec("mult_distribution", "Distribution multiplier (+18~+24m)", "float", 0.7, 0.1, 1.5, 0.05,
                     "정점 근방 위험 회피. 0.7 = 30% 사이즈 축소."),
            ParamSpec("mult_markdown", "Markdown multiplier (+30~+42m)", "float", 0.5, 0.1, 1.0, 0.05,
                     "베어마켓 자본 보전. 0.5 = 절반 사이즈."),
        ),
    ),
    "ensemble": StrategyMeta(
        cls=WeightedEnsemble,
        label="앙상블 (추세 + 평균회귀 가중 결합)",
        params=(
            ParamSpec("w_volatility_breakout", "변동성 돌파 가중치", "float", 0.0, 0.0, 1.0, 0.05,
                     "Larry K=0.5 원안 가중치. 디폴트 0 (단독 수익률 음수)."),
            ParamSpec("w_ma_cross", "MA 크로스 가중치", "float", 0.0, 0.0, 1.0, 0.05,
                     "MA(20/60) 가중치."),
            ParamSpec("w_rsi", "RSI 가중치", "float", 0.2, 0.0, 1.0, 0.05,
                     "Walk-forward OOS Sharpe 0.70, 두 번째 robust."),
            ParamSpec("w_crsi", "CRSI 가중치", "float", 0.3, 0.0, 1.0, 0.05,
                     "Walk-forward OOS Sharpe 1.15, 가장 robust."),
            ParamSpec("w_donchian_atr", "Donchian-ATR 가중치", "float", 0.3, 0.0, 1.0, 0.05,
                     "추세 추종 절대수익 1위, MDD 보완을 위해 평균회귀와 결합."),
            ParamSpec("w_tsmom", "TSMOM 가중치", "float", 0.2, 0.0, 1.0, 0.05,
                     "변동성 타겟팅 모멘텀. BTC Sharpe 1.04."),
            ParamSpec("w_larry_atr", "Larry+ATR 가중치", "float", 0.0, 0.0, 1.0, 0.05,
                     "변동성 돌파 + ATR Trail. OOS decay 큼, 디폴트 0."),
            ParamSpec("threshold", "진입 임계값", "float", 0.5, 0.0, 1.0, 0.05,
                     "가중평균 신호가 이 값 이상이면 매수. 0이면 연속 포지션 모드."),
        ),
    ),
}

# 호환 유지용 별칭
STRATEGIES: dict[str, type[Strategy]] = {k: v.cls for k, v in REGISTRY.items()}

__all__ = [
    "Strategy", "Signal", "ParamSpec", "StrategyMeta", "REGISTRY", "STRATEGIES",
    "VolatilityBreakout", "MACross", "RSIStrategy", "ConnorsRSI", "DonchianATR",
    "VolTargetedTSMOM", "LarryATR", "WeightedEnsemble", "CycleAwareEnsemble",
]