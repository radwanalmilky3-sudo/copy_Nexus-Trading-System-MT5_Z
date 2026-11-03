"""Separated backtest/live hooks that emit research features only."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Iterable

from services.nexus_news.research_integration.contracts import NewsEvent
from services.nexus_news.research_integration.windows import EventWindowFeatures, WindowSpec, build_event_windows
from .policy import NewsResearchPolicy, unconfirmed_news_policy


class NewsHookMode(StrEnum):
    BACKTEST = "backtest"
    LIVE = "live"


@dataclass(frozen=True, slots=True)
class NewsHookResult:
    mode: NewsHookMode
    decision_time: datetime
    features: tuple[EventWindowFeatures, ...]
    policies: tuple[NewsResearchPolicy, ...]
    research_only: bool = True
    trade_allowed: bool = False

    def __post_init__(self) -> None:
        if self.decision_time.tzinfo is None or self.decision_time.utcoffset() is None:
            raise ValueError("decision_time must be timezone-aware")
        if self.research_only is not True or self.trade_allowed is not False:
            raise ValueError("news hook results cannot authorize trading")

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "decision_time": self.decision_time.astimezone(timezone.utc).isoformat(),
            "features": [feature.as_dict() for feature in self.features],
            "policies": [
                {"research_only": p.research_only, "trade_allowed": p.trade_allowed,
                 "directional_research_allowed": p.directional_research_allowed, "reason": p.reason}
                for p in self.policies
            ],
            "research_only": True, "trade_allowed": False,
        }


class _NewsHook:
    mode: NewsHookMode

    def __init__(self, *, window: WindowSpec = WindowSpec("default")) -> None:
        self.window = window

    def evaluate(self, events: Iterable[NewsEvent], decision_time: datetime) -> NewsHookResult:
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            raise ValueError("decision_time must be timezone-aware")
        decision = decision_time.astimezone(timezone.utc)
        items = tuple(events)
        return NewsHookResult(
            mode=self.mode, decision_time=decision,
            features=build_event_windows(items, decision, spec=self.window),
            policies=tuple(unconfirmed_news_policy(event) for event in items),
        )


class BacktestNewsHook(_NewsHook):
    """Historical mode: only as-of-visible events enter features."""
    mode = NewsHookMode.BACKTEST


class LiveNewsHook(_NewsHook):
    """Live mode with the same no-look-ahead contract as backtest."""
    mode = NewsHookMode.LIVE


def apply_news_hook(events: Iterable[NewsEvent], decision_time: datetime, *,
                    mode: NewsHookMode | str,
                    window: WindowSpec = WindowSpec("default")) -> NewsHookResult:
    selected = NewsHookMode(mode)
    hook = BacktestNewsHook if selected is NewsHookMode.BACKTEST else LiveNewsHook
    return hook(window=window).evaluate(events, decision_time)


__all__ = ["BacktestNewsHook", "LiveNewsHook", "NewsHookMode",
           "NewsHookResult", "apply_news_hook"]
