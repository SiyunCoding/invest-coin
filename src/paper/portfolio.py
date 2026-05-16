"""가상 포트폴리오 + 리밸런싱 로직.

연속 포지션 모드(target_weight ∈ [0, 1])를 지원.
수수료 + 슬리피지는 거래 시점에 차감, cost basis는 가중평균.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Portfolio:
    cash: float
    qty: float = 0.0
    avg_cost: float = 0.0
    fee_rate: float = 0.001
    slippage_rate: float = 0.0005

    def mark_to_market(self, price: float) -> float:
        return self.cash + self.qty * price

    def rebalance(
        self,
        target_weight: float,
        price: float,
        time: datetime,
        min_rebalance_frac: float = 0.01,
    ) -> Optional[dict]:
        """target_weight 비율로 사이즈 맞춤. 임계값 미만 변동은 스킵.

        Returns: 거래 dict (체결 시) 또는 None (스킵).
        """
        if not 0.0 <= target_weight <= 1.0:
            raise ValueError(f"target_weight must be in [0, 1], got {target_weight}")
        if price <= 0:
            return None

        equity = self.mark_to_market(price)
        target_value = equity * target_weight
        current_value = self.qty * price
        delta_value = target_value - current_value

        # 너무 작은 리밸런싱(수수료만 까임)은 무시
        if abs(delta_value) < equity * min_rebalance_frac:
            return None

        cost_rate = self.fee_rate + self.slippage_rate

        if delta_value > 0:
            # 매수: cash 한도 내에서 gross_value 결정
            gross_value = delta_value
            total_cost = gross_value * (1 + cost_rate)
            if total_cost > self.cash:
                gross_value = self.cash / (1 + cost_rate)
                total_cost = self.cash
            fee = gross_value * cost_rate
            buy_qty = gross_value / price
            new_qty = self.qty + buy_qty
            if new_qty > 0:
                self.avg_cost = (self.avg_cost * self.qty + price * buy_qty) / new_qty
            self.qty = new_qty
            self.cash -= total_cost
            return {
                "time": time.isoformat(),
                "side": "buy",
                "qty": buy_qty,
                "price": price,
                "value": gross_value,
                "fee": fee,
            }
        else:
            # 매도: 보유 수량 한도 내
            gross_value = -delta_value
            sell_qty = gross_value / price
            if sell_qty > self.qty:
                sell_qty = self.qty
                gross_value = sell_qty * price
            fee = gross_value * cost_rate
            proceeds = gross_value - fee
            self.qty -= sell_qty
            self.cash += proceeds
            if self.qty < 1e-10:
                self.qty = 0.0
                self.avg_cost = 0.0
            return {
                "time": time.isoformat(),
                "side": "sell",
                "qty": sell_qty,
                "price": price,
                "value": gross_value,
                "fee": fee,
            }
