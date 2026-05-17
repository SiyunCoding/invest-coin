# Live Executor 통합 테스트 결과

실행: `2026-05-17 19:16:17 UTC`
결과: **6/6 통과**

## 시나리오 결과

| # | 시나리오 | Expected | Actual | 결과 |
|---|---|---|---|---|
| 1 | Test 1: 0% → 25% (첫 매수) | buy | buy | ✅ |
| 2 | Test 2: 25% → 50% (추가 매수) | buy | buy | ✅ |
| 3 | Test 3: 50% → 30% (부분 매도) | sell | sell | ✅ |
| 4 | Test 4: 30% → 0% (전량 매도) | sell | sell | ✅ |
| 5 | Test 5: 0% → 0% (중복 요청, 스킵 예상) | skip | skip | ✅ |
| 6 | Test 6: 0% → 0.001 (hysteresis 미만, 스킵 예상) | skip | skip | ✅ |

## 상세 로그

```
======================================================================
Live Executor 통합 테스트 (Binance Testnet)
======================================================================

Symbol filters:
  lot_step: 0.00001000
  min_qty: 0.00001000
  max_qty: 9000.00000000
  price_step: 0.01000000
  min_notional: 5.00000000

Initial: BTC=0.00000000, USDT=88,041.4400, price=$78,244.77, equity=$88,041.44

=== Test 1: 0% → 25% (첫 매수) ===
  target_weight = 0.25, min_rebalance_frac = 0.01
  Before: BTC=0.00000000, USDT=88,041.4400, price=$78,244.77, equity=$88,041.44
  Trade: BUY qty=0.28130000 @ $78,244.7800
         value=$22,010.2566, fee=0.00000000 BTC, order_id=4437287
  After:  BTC=0.28130000, USDT=66,031.1834, price=$78,244.78, equity=$88,041.44
  ✅ expected=buy, actual=buy

=== Test 2: 25% → 50% (추가 매수) ===
  target_weight = 0.5, min_rebalance_frac = 0.01
  Before: BTC=0.28130000, USDT=66,031.1834, price=$78,244.78, equity=$88,041.44
  Trade: BUY qty=0.28130000 @ $78,244.7800
         value=$22,010.2566, fee=0.00000000 BTC, order_id=4437289
  After:  BTC=0.56260000, USDT=44,020.9268, price=$78,244.78, equity=$88,041.44
  ✅ expected=buy, actual=buy

=== Test 3: 50% → 30% (부분 매도) ===
  target_weight = 0.3, min_rebalance_frac = 0.01
  Before: BTC=0.56260000, USDT=44,020.9268, price=$78,244.78, equity=$88,041.44
  Trade: SELL qty=0.22503000 @ $78,244.7700
         value=$17,607.4206, fee=0.00000000 USDT, order_id=4437293
  After:  BTC=0.33757000, USDT=61,628.3474, price=$78,249.69, equity=$88,043.10
  ✅ expected=sell, actual=sell

=== Test 4: 30% → 0% (전량 매도) ===
  target_weight = 0.0, min_rebalance_frac = 0.01
  Before: BTC=0.33757000, USDT=61,628.3474, price=$78,249.69, equity=$88,043.10
  Trade: SELL qty=0.33757000 @ $78,249.6800
         value=$26,414.7445, fee=0.00000000 USDT, order_id=4437337
  After:  BTC=0.00000000, USDT=88,043.0918, price=$78,249.69, equity=$88,043.09
  ✅ expected=sell, actual=sell

=== Test 5: 0% → 0% (중복 요청, 스킵 예상) ===
  target_weight = 0.0, min_rebalance_frac = 0.01
  Before: BTC=0.00000000, USDT=88,043.0918, price=$78,249.69, equity=$88,043.09
  Trade: SKIPPED (rebalance not needed)
  After:  BTC=0.00000000, USDT=88,043.0918, price=$78,249.69, equity=$88,043.09
  ✅ expected=skip, actual=skip

=== Test 6: 0% → 0.001 (hysteresis 미만, 스킵 예상) ===
  target_weight = 0.001, min_rebalance_frac = 0.01
  Before: BTC=0.00000000, USDT=88,043.0918, price=$78,249.69, equity=$88,043.09
  Trade: SKIPPED (rebalance not needed)
  After:  BTC=0.00000000, USDT=88,043.0918, price=$78,249.68, equity=$88,043.09
  ✅ expected=skip, actual=skip

======================================================================
Cleanup — 남은 BTC 정리
======================================================================

Final:    BTC=0.00000000, USDT=88,043.0918, price=$78,249.68, equity=$88,043.09
Initial:  BTC=0.00000000, USDT=88,041.4400, price=$78,244.77, equity=$88,041.44
Equity Δ: $+1.6518 (+0.0019%) — 슬리피지 + 수수료 누적

======================================================================
SUMMARY: 6/6 passed
======================================================================
  ✅ Test 1: 0% → 25% (첫 매수): expected=buy, actual=buy
  ✅ Test 2: 25% → 50% (추가 매수): expected=buy, actual=buy
  ✅ Test 3: 50% → 30% (부분 매도): expected=sell, actual=sell
  ✅ Test 4: 30% → 0% (전량 매도): expected=sell, actual=sell
  ✅ Test 5: 0% → 0% (중복 요청, 스킵 예상): expected=skip, actual=skip
  ✅ Test 6: 0% → 0.001 (hysteresis 미만, 스킵 예상): expected=skip, actual=skip
```