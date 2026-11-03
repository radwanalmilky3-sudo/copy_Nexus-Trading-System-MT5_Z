"""Fail-closed policy for research news outputs."""
from __future__ import annotations

from dataclasses import dataclass

from services.nexus_news.research_integration.contracts import NewsEvent


@dataclass(frozen=True, slots=True)
class NewsResearchPolicy:
    research_only: bool = True
    trade_allowed: bool = False
    directional_research_allowed: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        if self.research_only is not True or self.trade_allowed is not False:
            raise ValueError("research news hooks cannot authorize trading")


def unconfirmed_news_policy(event: NewsEvent) -> NewsResearchPolicy:
    if not event.confirmed:
        return NewsResearchPolicy(reason="unconfirmed_news_blocked")
    if not event.has_verified_provenance:
        return NewsResearchPolicy(reason="provenance_not_verified")
    if event.actual is None or event.forecast is None:
        return NewsResearchPolicy(reason="directional_surprise_missing")
    return NewsResearchPolicy(directional_research_allowed=True, reason="confirmed_for_research_only")


__all__ = ["NewsResearchPolicy", "unconfirmed_news_policy"]
