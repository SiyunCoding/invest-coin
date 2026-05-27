"""Binance 실 매매 모듈 (Spot Testnet + Futures Demo).

- Spot: testnet.binance.vision (현물 cycle_aware 일봉)
- Futures: demo-fapi.binance.com (선물 50x RSI 5m 스캘핑)
- source-of-truth = Binance 계정 (JSON은 거래 로그 + 히스토리만 보관)

환경 변수:
  - Spot Testnet: BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET
  - Spot Mainnet: BINANCE_API_KEY / BINANCE_API_SECRET
  - Futures Demo: BINANCE_FUTURES_TESTNET_API_KEY / BINANCE_FUTURES_TESTNET_API_SECRET
  - Futures Mainnet: BINANCE_FUTURES_API_KEY / BINANCE_FUTURES_API_SECRET
"""
from .client import get_client
from .executor import rebalance_to_target
from .futures_client import get_futures_client
from .futures_tick import run_futures_tick
from .tick import run_live_tick

__all__ = [
    "get_client",
    "rebalance_to_target",
    "run_live_tick",
    "get_futures_client",
    "run_futures_tick",
]
