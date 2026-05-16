"""WeightedEnsemble — 여러 sub-strategy 신호의 가중 평균.

설계 의도:
- Walk-forward 결과 단일 전략은 over-fit. 평균회귀 + 추세 추종을 함께 묶어 환경 변화에 적응.
- 각 sub-strategy의 신호([0, 1])에 가중치를 곱한 평균을 구하고, threshold 이상이면 long.
- threshold=0 이면 연속 포지션 모드(엔진이 0~1 사이 사이즈로 보유).

디폴트 가중치는 BTC walk-forward OOS Sharpe 기반 잠정값:
  CRSI 0.30, RSI 0.20, Donchian-ATR 0.30, TSMOM 0.20
  나머지는 0 (튜닝 의지가 있다면 슬라이더에서 올려보세요).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .base import Signal, Strategy
from .crsi import ConnorsRSI
from .donchian_atr import DonchianATR
from .larry_atr import LarryATR
from .ma_cross import MACross
from .rsi import RSIStrategy
from .tsmom import VolTargetedTSMOM
from .volatility_breakout import VolatilityBreakout


@dataclass
class WeightedEnsemble(Strategy):
    w_volatility_breakout: float = 0.0
    w_ma_cross: float = 0.0
    w_rsi: float = 0.2
    w_crsi: float = 0.3
    w_donchian_atr: float = 0.3
    w_tsmom: float = 0.2
    w_larry_atr: float = 0.0
    threshold: float = 0.5
    name: str = "ensemble"

    def _components(self):
        return [
            (self.w_volatility_breakout, VolatilityBreakout()),
            (self.w_ma_cross, MACross()),
            (self.w_rsi, RSIStrategy()),
            (self.w_crsi, ConnorsRSI()),
            (self.w_donchian_atr, DonchianATR()),
            (self.w_tsmom, VolTargetedTSMOM()),
            (self.w_larry_atr, LarryATR()),
        ]

    def generate_signals(self, ohlcv: pd.DataFrame) -> Signal:
        if not 0 <= self.threshold <= 1:
            raise ValueError("threshold must be in [0, 1]")
        comps = self._components()
        total_w = sum(w for w, _ in comps if w > 0)
        if total_w == 0:
            return pd.Series(0.0, index=ohlcv.index, name="signal")

        agg = pd.Series(0.0, index=ohlcv.index)
        for w, strategy in comps:
            if w <= 0:
                continue
            sig = strategy.generate_signals(ohlcv).reindex(ohlcv.index).fillna(0.0)
            agg = agg.add(w * sig.clip(0.0, 1.0), fill_value=0.0)
        weighted = agg / total_w

        # threshold 위만 살리되, 위에서는 연속 사이즈 유지 (TSMOM/LarryATR의 vol-sizing 보존)
        if self.threshold > 0:
            denom = max(1.0 - self.threshold, 1e-6)
            soft = ((weighted - self.threshold) / denom).clip(0.0, 1.0)
            return soft.rename("signal")
        return weighted.clip(0.0, 1.0).rename("signal")
