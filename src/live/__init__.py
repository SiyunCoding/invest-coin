"""Binance 실 매매 모듈 (Spot Testnet/Mainnet + Futures Demo).

- Spot: Trend Rotation 포트폴리오 (BTC 슬리브 + 월간 알트 유니버스, 일봉) — portfolio_tick
- Futures: demo-fapi.binance.com (선물 50x RSI 5m 스캘핑, 중단 권고 — tasks/lessons.md L13)
- source-of-truth = Binance 계정 (JSON은 거래 로그 + 히스토리만 보관)

환경 변수:
  - Spot Testnet: BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET
  - Spot Mainnet: BINANCE_API_KEY / BINANCE_API_SECRET
  - Futures Demo: BINANCE_FUTURES_TESTNET_API_KEY / BINANCE_FUTURES_TESTNET_API_SECRET
  - Futures Mainnet: BINANCE_FUTURES_API_KEY / BINANCE_FUTURES_API_SECRET
"""
from .client import get_client
from .futures_client import get_futures_client
from .futures_tick import run_futures_tick
from .portfolio_executor import rebalance_portfolio
from .portfolio_tick import run_portfolio_tick

__all__ = [
    "get_client",
    "rebalance_portfolio",
    "run_portfolio_tick",
    "get_futures_client",
    "run_futures_tick",
]
