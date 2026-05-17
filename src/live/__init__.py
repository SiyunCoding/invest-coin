"""Binance Testnet/Mainnet 실 매매 모듈.

- 실제 Binance API 호출 (testnet 또는 mainnet)
- source-of-truth = Binance 계정 (JSON은 거래 로그 + 히스토리만 보관)
- LOT_SIZE / PRICE_FILTER / MIN_NOTIONAL 등 거래소 규칙 자동 적용
- 부분 체결 / 주문 거부 / 레이트리밋 처리

환경 변수:
  - BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET (testnet=True 시)
  - BINANCE_API_KEY / BINANCE_API_SECRET (testnet=False, 실거래)
"""
from .client import get_client
from .executor import rebalance_to_target
from .tick import run_live_tick

__all__ = ["get_client", "rebalance_to_target", "run_live_tick"]
