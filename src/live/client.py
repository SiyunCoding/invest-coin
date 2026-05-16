"""Binance Client 팩토리. Testnet/Mainnet 토글.

테스트넷:
  - URL: testnet.binance.vision
  - 키 발급: https://testnet.binance.vision (GitHub OAuth 로그인)
  - 가입 시 가짜 USDT/BTC 등 무료 지급
  - Geo-block 없음 (개발자용)

메인넷: 실거래용. 안전장치 통과 후에만 사용.
"""
from __future__ import annotations

import os

from binance.client import Client


def get_client(testnet: bool = True) -> Client:
    """python-binance Client 인스턴스 반환.

    testnet=True (디폴트): testnet.binance.vision 사용. 가짜 돈.
    testnet=False: 실거래용. 신중히.
    """
    if testnet:
        key = os.environ.get("BINANCE_TESTNET_API_KEY")
        secret = os.environ.get("BINANCE_TESTNET_API_SECRET")
        if not key or not secret:
            raise RuntimeError(
                "BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET 환경 변수가 필요.\n"
                "  로컬: PowerShell 에서 $env:BINANCE_TESTNET_API_KEY='...'\n"
                "  GHA: repo Settings → Secrets → Actions 에 추가"
            )
        return Client(key, secret, testnet=True)
    else:
        key = os.environ.get("BINANCE_API_KEY")
        secret = os.environ.get("BINANCE_API_SECRET")
        if not key or not secret:
            raise RuntimeError(
                "BINANCE_API_KEY / BINANCE_API_SECRET 환경 변수가 필요 (실거래용)."
            )
        return Client(key, secret)
