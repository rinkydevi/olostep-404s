from dataclasses import dataclass


class BudgetExceeded(Exception):
    pass


@dataclass
class Budget:
    ceiling: int | None = None
    unlimited: bool = False
    credits_consumed: int = 0

    def can_consume(self, amount: int = 1) -> bool:
        if self.ceiling is None:
            return self.unlimited
        return self.credits_consumed + amount <= self.ceiling

    def consume(self, amount: int = 1) -> None:
        if not self.can_consume(amount):
            raise BudgetExceeded(
                f"would exceed budget: {self.credits_consumed} + {amount} > {self.ceiling}"
            )
        self.credits_consumed += amount
