"""Research-only news hooks; no execution, risk, or service side effects."""

from .hooks import BacktestNewsHook, LiveNewsHook, NewsHookResult, apply_news_hook
from .policy import NewsResearchPolicy, unconfirmed_news_policy

__all__ = ["BacktestNewsHook", "LiveNewsHook", "NewsHookResult",
           "NewsResearchPolicy", "apply_news_hook", "unconfirmed_news_policy"]
