"""전략 추상 클래스.

각 전략은 OHLCV DataFrame을 받아 같은 길이의 Signal Series를 반환한다.
- 1.0  → 다음 봉 시작에 풀포지션 보유
- 0.0  → 무포지션 (현금)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

Signal = pd.Series


@dataclass
class Strategy(ABC):
    """모든 전략의 베이스. 파라미터는 서브클래스의 dataclass 필드로 정의."""

    name: str = "base"

    @abstractmethod
    def generate_signals(self, ohlcv: pd.DataFrame) -> Signal:
        """OHLCV(인덱스: open_time UTC, 컬럼: open/high/low/close/volume)를 받아
        포지션 비중 시계열을 반환. 인덱스는 입력과 동일.

        주의: lookahead bias 방지를 위해 i 시점의 신호는 i 시점까지의 정보만 사용해야 한다.
        백테스트 엔진은 신호를 한 칸 미뤄 다음 봉에 진입하는 것으로 가정한다.
        """
        raise NotImplementedError
