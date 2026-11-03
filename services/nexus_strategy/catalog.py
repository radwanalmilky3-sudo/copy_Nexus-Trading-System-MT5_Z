"""Reference strategy definitions distilled from fx-trading-system-main."""

from __future__ import annotations

from shared.strategy_contracts import (
    NewsHookAction,
    NewsRegimeHook,
    ParameterSelectionScope,
    ParameterSet,
    StrategyDefinition,
    StrategyFamily,
)


REFERENCE_STRATEGIES: tuple[StrategyDefinition, ...] = (
    StrategyDefinition(
        strategy_id="regime_mean_reversion",
        version="reference-1",
        display_name="Regime mean reversion",
        family=StrategyFamily.MEAN_REVERSION,
        description="Z-score and RSI exhaustion entries gated to a non-trending regime.",
        entry_rule="rolling_zscore and RSI extreme with trend-strength gate",
        exit_rule="ATR stop/target or maximum holding horizon",
        parameter_set_id="regime_mean_reversion.default",
        regime_labels=("ranging",),
        news_regime_hook_ids=("high_impact_news_blackout",),
    ),
    StrategyDefinition(
        strategy_id="trend_pullback",
        version="reference-1",
        display_name="Trend pullback",
        family=StrategyFamily.TREND,
        description="EMA trend alignment followed by a pullback continuation entry.",
        entry_rule="fast/slow EMA alignment plus RSI pullback reclaim",
        exit_rule="ATR stop/target or maximum holding horizon",
        parameter_set_id="trend_pullback.default",
        regime_labels=("trending_up", "trending_down"),
        news_regime_hook_ids=("high_impact_news_blackout",),
    ),
    StrategyDefinition(
        strategy_id="session_breakout",
        version="reference-1",
        display_name="Session breakout",
        family=StrategyFamily.BREAKOUT,
        description="Break of the completed Asian range during the London session.",
        entry_rule="completed Asian range plus ATR breakout buffer",
        exit_rule="ATR stop/target or session holding limit",
        parameter_set_id="session_breakout.default",
        regime_labels=("breakout",),
        news_regime_hook_ids=("high_impact_news_blackout",),
    ),
    StrategyDefinition(
        strategy_id="false_breakout_reversal",
        version="reference-1",
        display_name="False breakout reversal",
        family=StrategyFamily.MEAN_REVERSION,
        description="Fade a rejected multi-day range break outside strong trends.",
        entry_rule="Donchian rejection with momentum and trend-strength filter",
        exit_rule="ATR stop/target or maximum holding horizon",
        parameter_set_id="false_breakout_reversal.default",
        regime_labels=("ranging",),
        news_regime_hook_ids=("high_impact_news_blackout",),
    ),
    StrategyDefinition(
        strategy_id="currency_strength_reversion",
        version="reference-1",
        display_name="Currency strength reversion",
        family=StrategyFamily.MULTICURRENCY,
        description="Pair exhaustion confirmed by the broader currency graph.",
        entry_rule="currency-strength imbalance plus pair z-score",
        exit_rule="ATR stop/target or maximum holding horizon",
        parameter_set_id="currency_strength_reversion.default",
        regime_labels=("ranging", "cross_asset_confirmation"),
        news_regime_hook_ids=("high_impact_news_blackout",),
    ),
    StrategyDefinition(
        strategy_id="cointegration_spread",
        version="reference-1",
        display_name="Cointegration spread",
        family=StrategyFamily.MULTICURRENCY,
        description="Pair spread extremes gated by rolling OLS and cointegration evidence.",
        entry_rule="rolling spread z-score after cointegration acceptance",
        exit_rule="spread mean reversion, ATR stop/target, or maximum holding horizon",
        parameter_set_id="cointegration_spread.default",
        regime_labels=("ranging", "cointegration_stable"),
        news_regime_hook_ids=("high_impact_news_blackout",),
    ),
)


def _parameter_set(
    strategy_id: str,
    parameters: dict[str, int | float | str | bool],
) -> ParameterSet:
    return ParameterSet(
        parameter_set_id=f"{strategy_id}.default",
        strategy_id=strategy_id,
        version="reference-1",
        parameters=parameters,
        selection_scope=ParameterSelectionScope.TRAIN_ONLY,
        selected_in_run_id="catalog-only",
        selection_metric="net_sharpe",
    )


REFERENCE_PARAMETER_SETS: tuple[ParameterSet, ...] = (
    _parameter_set(
        "regime_mean_reversion",
        {"lookback": 30, "entry_z": 1.65, "max_trend_strength": 1.25},
    ),
    _parameter_set("trend_pullback", {"fast": 20, "slow": 60}),
    _parameter_set(
        "session_breakout",
        {"breakout_buffer_atr": 0.08, "max_asian_range_atr": 2.2},
    ),
    _parameter_set(
        "false_breakout_reversal",
        {"range_bars": 18, "max_trend_strength": 1.4},
    ),
    _parameter_set(
        "currency_strength_reversion",
        {"lookback": 18, "strength_z": 1.25, "pair_z": 1.35},
    ),
    _parameter_set(
        "cointegration_spread",
        {"lookback": 120, "entry_z": 1.8, "exit_z": 0.45},
    ),
)


REFERENCE_NEWS_HOOKS: tuple[NewsRegimeHook, ...] = (
    NewsRegimeHook(
        hook_id="high_impact_news_blackout",
        name="High-impact news blackout",
        action=NewsHookAction.BLOCK_ENTRIES,
        impact_levels=("high",),
        pre_event_minutes=30,
        post_event_minutes=30,
        require_pit_available_time=True,
    ),
)


__all__ = [
    "REFERENCE_NEWS_HOOKS",
    "REFERENCE_PARAMETER_SETS",
    "REFERENCE_STRATEGIES",
]
