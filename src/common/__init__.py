"""trading 공유 모듈 — state JSON I/O + HTML 대시보드.

live tick 이 이 모듈들을 쓴다. (이전에는 src/paper/ 안에 있었지만 paper 폐지되면서 이전)
"""
from .dashboard import render_dashboard
from .state import init_state, load_state, save_state

__all__ = ["render_dashboard", "init_state", "load_state", "save_state"]
