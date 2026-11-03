"""Pure strategy/backtest contracts and research-only planning helpers.

Nothing in this package starts a service, reads a data source, imports a
dataset, or executes a trade/backtest.  Runners may consume the contracts
later after their own data and approval boundaries are established.
"""

from .anti_leakage import audit_point_in_time_records
from .catalog import REFERENCE_NEWS_HOOKS, REFERENCE_PARAMETER_SETS, REFERENCE_STRATEGIES
from .news_regime import evaluate_news_regime
from .walk_forward import build_walk_forward_windows

__all__ = [
    "REFERENCE_PARAMETER_SETS",
    "REFERENCE_STRATEGIES",
    "REFERENCE_NEWS_HOOKS",
    "audit_point_in_time_records",
    "build_walk_forward_windows",
    "evaluate_news_regime",
]
