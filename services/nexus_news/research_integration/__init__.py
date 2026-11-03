"""Research-only, point-in-time news integration."""

from .contracts import BlackoutWindow, ImpactLevel, NewsEvent
from .normalization import EconomicCalendarNormalizer, normalize_calendar_event
from .windows import EventWindowFeatures, WindowSpec, build_event_window_features

__all__ = ["BlackoutWindow", "ImpactLevel", "NewsEvent", "EconomicCalendarNormalizer",
           "normalize_calendar_event", "EventWindowFeatures", "WindowSpec",
           "build_event_window_features"]
