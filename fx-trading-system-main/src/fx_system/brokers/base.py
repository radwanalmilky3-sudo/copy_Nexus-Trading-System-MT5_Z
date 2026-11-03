from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PracticeBroker(ABC):
    @abstractmethod
    def account_summary(self) -> dict[str, Any]: ...

    @abstractmethod
    def open_positions(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def submit_market_order(
        self,
        symbol: str,
        units: int,
        stop_loss: float,
        take_profit: float,
        client_id: str,
        confirm_practice: bool = False,
    ) -> dict[str, Any]: ...
