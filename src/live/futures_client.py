"""Binance Futures Demo / Mainnet Client 팩토리.

Binance가 testnet.binancefuture.com → demo-fapi.binance.com 으로 옮김 (2026~).
python-binance의 testnet=True 플래그가 옛 URL을 가리키므로 FUTURES_URL을
수동 오버라이드해야 함.

Demo:
  - URL: https://demo-fapi.binance.com
  - 가입: testnet.binancefuture.com (자동 리다이렉트 → demo-trading UI)
  - 가짜 USDT 자동 지급

환경 변수:
  - BINANCE_FUTURES_TESTNET_API_KEY / BINANCE_FUTURES_TESTNET_API_SECRET (demo=True)
  - BINANCE_FUTURES_API_KEY / BINANCE_FUTURES_API_SECRET (demo=False, 실거래)
"""
from __future__ import annotations

import os

from binance.client import Client

# python-binance가 FUTURES_URL + '/v{N}/{path}' 로 조립하므로 base에 /fapi 포함 필수.
DEMO_FUTURES_URL = "https://demo-fapi.binance.com/fapi"
DEMO_FUTURES_DATA_URL = "https://demo-fapi.binance.com/futures/data"


def get_futures_client(demo: bool = True) -> Client:
    """python-binance Client + Futures Demo URL 오버라이드."""
    if demo:
        key = os.environ.get("BINANCE_FUTURES_TESTNET_API_KEY")
        secret = os.environ.get("BINANCE_FUTURES_TESTNET_API_SECRET")
        if not key or not secret:
            raise RuntimeError(
                "BINANCE_FUTURES_TESTNET_API_KEY / BINANCE_FUTURES_TESTNET_API_SECRET 환경 변수가 필요."
            )
        client = Client(key, secret)
        client.FUTURES_URL = DEMO_FUTURES_URL
        # FUTURES_DATA_URL은 일부 통계 API (open interest 등)에서 사용
        if hasattr(client, "FUTURES_DATA_URL"):
            client.FUTURES_DATA_URL = DEMO_FUTURES_DATA_URL
        return client
    else:
        key = os.environ.get("BINANCE_FUTURES_API_KEY")
        secret = os.environ.get("BINANCE_FUTURES_API_SECRET")
        if not key or not secret:
            raise RuntimeError(
                "BINANCE_FUTURES_API_KEY / BINANCE_FUTURES_API_SECRET 환경 변수가 필요 (실거래용)."
            )
        return Client(key, secret)
