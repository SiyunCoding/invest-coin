"""Binance 현물 실 매매 모듈 — Trend Rotation 포트폴리오 (BTC 슬리브 + 월간 알트 유니버스, 일봉).

- source-of-truth = Binance 계정 (JSON은 거래 로그 + 히스토리만 보관)
- 선물 스캘퍼는 2026-10 중단·삭제 (손익분기 승률 > 랜덤워크 승률, tasks/lessons.md L16)

환경 변수:
  - Spot Testnet: BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET
  - Spot Mainnet: BINANCE_API_KEY / BINANCE_API_SECRET
"""
from .client import get_client
from .portfolio_executor import rebalance_portfolio
from .portfolio_tick import run_portfolio_tick

__all__ = ["get_client", "rebalance_portfolio", "run_portfolio_tick"]
