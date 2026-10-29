"""멀티코인 Trend Rotation 포트폴리오 (유니버스 선정 + 목표 비중)."""
from .allocator import TrendRotationConfig, apply_band, target_weights, weights_from_signals
from .universe import is_eligible_symbol, select_universe, should_drop

__all__ = [
    "TrendRotationConfig", "apply_band", "target_weights", "weights_from_signals",
    "is_eligible_symbol", "select_universe", "should_drop",
]
