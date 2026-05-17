"""페이퍼/라이브 트레이딩 상태 영속화 (JSON).

src/live/tick.py 도 이 모듈을 공유. 'paper' 디렉토리에 있지만 paper 전용은 아님.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def load_state(path: Path) -> Optional[dict]:
    """파일이 없으면 None. 있으면 dict."""
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def init_state(config: dict, started_at: str) -> dict:
    return {
        "config": config,
        "cash": config["initial_capital"],
        "position": {"qty": 0.0, "avg_cost": 0.0},
        "trades": [],
        "history": [],
        "peak_equity": config["initial_capital"],
        "started_at": started_at,
        "last_tick": None,
        "last_price": None,
        "last_signal": None,
        "last_bar_time": None,
    }
