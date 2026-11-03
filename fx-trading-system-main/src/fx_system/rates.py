from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping

import pandas as pd

from .models import CurrencyPair


class FXRateGraph:
    """Converts arbitrary portfolio currencies through currently available FX crosses."""

    def __init__(self, data: Mapping[str, pd.DataFrame], account_currency: str = "USD") -> None:
        self.data = data
        self.account_currency = account_currency

    def prices_at(self, timestamp: pd.Timestamp, field: str = "close") -> dict[str, float]:
        prices: dict[str, float] = {}
        for symbol, frame in self.data.items():
            location = frame.index.searchsorted(timestamp, side="right") - 1
            if location >= 0:
                prices[symbol] = float(frame.iloc[location][field])
        return prices

    def prices_at_open(self, timestamp: pd.Timestamp) -> dict[str, float]:
        """Prices knowable at an event open: exact-bar open, otherwise prior close."""
        prices: dict[str, float] = {}
        for symbol, frame in self.data.items():
            location = frame.index.searchsorted(timestamp, side="left")
            if location < len(frame) and frame.index[location] == timestamp:
                prices[symbol] = float(frame.iloc[location]["open"])
            elif location > 0:
                prices[symbol] = float(frame.iloc[location - 1]["close"])
        return prices

    @staticmethod
    def convert_with_prices(
        amount: float,
        source: str,
        target: str,
        prices: Mapping[str, float],
    ) -> float:
        if source == target:
            return amount
        graph: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for symbol, price in prices.items():
            if price <= 0:
                continue
            pair = CurrencyPair.parse(symbol)
            graph[pair.base].append((pair.quote, price))
            graph[pair.quote].append((pair.base, 1 / price))
        queue: deque[tuple[str, float]] = deque([(source, 1.0)])
        visited = {source}
        while queue:
            currency, rate = queue.popleft()
            for neighbor, edge_rate in graph.get(currency, []):
                if neighbor in visited:
                    continue
                next_rate = rate * edge_rate
                if neighbor == target:
                    return amount * next_rate
                visited.add(neighbor)
                queue.append((neighbor, next_rate))
        raise ValueError(f"No conversion path from {source} to {target}")

    def convert(
        self,
        amount: float,
        source: str,
        target: str,
        timestamp: pd.Timestamp,
        field: str = "close",
    ) -> float:
        return self.convert_with_prices(amount, source, target, self.prices_at(timestamp, field))
