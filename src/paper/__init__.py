"""페이퍼 트레이딩 (모의투자) 모듈.

가상 포트폴리오로 cycle_aware 신호를 따라 매매하면서 실시간 검증.
GitHub Actions가 매일 UTC 00:30에 한 번 tick을 돌린다.
"""
from .portfolio import Portfolio
from .state import load_state, save_state
from .tick import run_tick

__all__ = ["Portfolio", "load_state", "save_state", "run_tick"]
