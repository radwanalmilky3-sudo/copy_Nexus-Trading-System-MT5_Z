from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping

import numpy as np

from .config import EnsembleConfig
from .models import Side, Signal


class SignalEnsembler:
    def __init__(
        self,
        config: EnsembleConfig,
        strategy_weights: Mapping[str, float],
    ) -> None:
        self.config = config
        self.strategy_weights = strategy_weights

    def combine(self, signals: Iterable[Signal]) -> list[Signal]:
        signal_list = list(signals)
        expected_group_size = Counter(
            signal.group_id for signal in signal_list if signal.group_id is not None
        )
        groups: dict[tuple[object, str], list[Signal]] = defaultdict(list)
        for signal in signal_list:
            groups[(signal.timestamp, signal.symbol)].append(signal)

        combined: list[Signal] = []
        for (_, _), items in sorted(groups.items(), key=lambda item: item[0]):
            weighted = [
                (item, self.strategy_weights.get(item.strategy, 1.0) * item.confidence)
                for item in items
            ]
            denominator = sum(weight for _, weight in weighted)
            if denominator <= 0:
                continue
            directional = sum(int(item.side) * weight for item, weight in weighted)
            vote = abs(directional) / denominator
            if vote < self.config.minimum_vote:
                continue
            side = Side.LONG if directional > 0 else Side.SHORT
            supporters = [(item, weight) for item, weight in weighted if item.side == side]
            if not supporters:
                continue
            support_weight = sum(weight for _, weight in supporters)
            confidence = (
                sum(item.confidence * weight for item, weight in supporters) / support_weight
            )
            confidence *= 1 - self.config.disagreement_penalty * (1 - vote)
            if confidence < self.config.minimum_confidence:
                continue
            dominant = max(supporters, key=lambda value: value[1])[0]
            names = sorted({item.strategy for item, _ in supporters})
            linked_groups = {item.group_id for item, _ in supporters if item.group_id is not None}
            group_id = next(iter(linked_groups)) if len(linked_groups) == 1 else None
            combined.append(
                Signal(
                    timestamp=dominant.timestamp,
                    symbol=dominant.symbol,
                    side=side,
                    confidence=float(np.clip(confidence, 0, 1)),
                    strategy=names[0] if len(names) == 1 else f"ensemble[{'+'.join(names)}]",
                    atr=sum(item.atr * weight for item, weight in supporters) / support_weight,
                    stop_atr=sum(item.stop_atr * weight for item, weight in supporters)
                    / support_weight,
                    target_atr=sum(item.target_atr * weight for item, weight in supporters)
                    / support_weight,
                    max_holding_hours=min(item.max_holding_hours for item, _ in supporters),
                    reason=" | ".join(item.reason for item, _ in supporters),
                    group_id=group_id,
                )
            )
        actual_group_size = Counter(
            signal.group_id for signal in combined if signal.group_id is not None
        )
        return [
            signal
            for signal in combined
            if signal.group_id is None
            or actual_group_size[signal.group_id] == expected_group_size[signal.group_id]
        ]
