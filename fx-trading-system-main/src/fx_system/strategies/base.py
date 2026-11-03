from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

import pandas as pd

from ..models import Signal


class Strategy(ABC):
    name: str

    @abstractmethod
    def generate(self, data: Mapping[str, pd.DataFrame]) -> list[Signal]:
        """Generate close-of-bar signals. The engine executes them at a later bar open."""
