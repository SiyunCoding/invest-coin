"""트레이딩 공유 모듈 — state JSON I/O + HTML 대시보드.

live tick이 매 사이클마다 사용. data/live_state.json 로드/저장, docs/live_dashboard.html 생성.
"""
from .dashboard import render_dashboard
from .state import init_state, load_state, save_state

__all__ = ["render_dashboard", "init_state", "load_state", "save_state"]
