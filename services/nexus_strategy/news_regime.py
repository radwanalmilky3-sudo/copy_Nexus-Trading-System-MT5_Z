"""PIT-aware news and calendar hooks for future strategy runners."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from shared.strategy_contracts import (
    NewsEvent,
    NewsHookAction,
    NewsRegimeDecision,
    NewsRegimeHook,
)


def evaluate_news_regime(
    hooks: Iterable[NewsRegimeHook],
    events: Iterable[NewsEvent],
    *,
    decision_time: datetime,
) -> NewsRegimeDecision:
    """Apply declared hooks to events known at ``decision_time`` only.

    Future scheduled events are ignored unless the hook explicitly opts into
    them and their ``available_time`` is already PIT-eligible.  This makes the
    news layer a policy hook rather than an implicit source of look-ahead.
    """

    if decision_time.tzinfo is None or decision_time.utcoffset() is None:
        raise ValueError("decision_time must be timezone-aware")

    hook_values = tuple(hooks)
    event_values = tuple(events)
    matched_ids: list[str] = []
    active_hook_ids: list[str] = []
    labels: list[str] = []
    block_entries = False
    exposure_multiplier = 1.0
    pit_eligible = True

    for hook in hook_values:
        for event in event_values:
            if event.available_time > decision_time:
                pit_eligible = False
                continue
            if event.event_time > decision_time and not (
                event.scheduled and hook.use_scheduled_events
            ):
                continue
            if hook.impact_levels and event.impact.lower() not in {
                level.lower() for level in hook.impact_levels
            }:
                continue
            if hook.currencies and not set(hook.currencies).intersection(event.currencies):
                continue

            lower = decision_time - timedelta(minutes=hook.pre_event_minutes)
            upper = decision_time + timedelta(minutes=hook.post_event_minutes)
            if not lower <= event.event_time <= upper:
                continue

            if event.event_id not in matched_ids:
                matched_ids.append(event.event_id)
            if hook.hook_id not in active_hook_ids:
                active_hook_ids.append(hook.hook_id)
            if hook.regime_label not in labels:
                labels.append(hook.regime_label)
            if hook.action == NewsHookAction.BLOCK_ENTRIES:
                block_entries = True
            elif hook.action == NewsHookAction.SCALE_EXPOSURE:
                exposure_multiplier = min(exposure_multiplier, hook.exposure_multiplier)
            break

    return NewsRegimeDecision(
        decision_time=decision_time,
        matched_event_ids=tuple(matched_ids),
        active_hook_ids=tuple(active_hook_ids),
        regime_labels=tuple(labels),
        block_entries=block_entries,
        exposure_multiplier=exposure_multiplier,
        pit_eligible=pit_eligible,
    )


__all__ = ["evaluate_news_regime"]
