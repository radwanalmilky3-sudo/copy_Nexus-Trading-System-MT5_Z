from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from .factor_config import FactorDiscoverySettings


@dataclass(frozen=True)
class GeneratedFactor:
    name: str
    family: str
    directional: bool
    description: str
    expression: str
    operator: str
    parents: tuple[str, ...]
    window: int | None
    complexity: int
    generation_order: int


def _definition_direction(definitions: dict[str, Any], name: str) -> bool:
    definition = definitions[name]
    return bool(
        definition.directional
        if hasattr(definition, "directional")
        else definition["directional"]
    )


def _grouped_transform(
    panel: pd.DataFrame,
    source: str,
    operator: str,
    window: int,
) -> pd.Series:
    grouped = panel.groupby("_symbol", sort=False)[source]
    if operator == "delta":
        return grouped.diff(window)
    if operator == "ts_mean":
        return grouped.transform(lambda values: values.rolling(window, min_periods=window).mean())
    if operator == "ts_std":
        return grouped.transform(
            lambda values: values.rolling(window, min_periods=window).std(ddof=0)
        )
    if operator == "ts_zscore":
        mean = grouped.transform(lambda values: values.rolling(window, min_periods=window).mean())
        scale = grouped.transform(
            lambda values: values.rolling(window, min_periods=window).std(ddof=0)
        ).replace(0, np.nan)
        return (panel[source] - mean) / scale
    raise ValueError(f"Unsupported factor DSL operator: {operator}")


def generate_discovery_factors(
    panel: pd.DataFrame,
    definitions: dict[str, Any],
    settings: FactorDiscoverySettings,
) -> tuple[pd.DataFrame, list[GeneratedFactor]]:
    """Generate a deterministic, budgeted expression set without using any target values."""
    if not settings.enabled:
        return panel, []
    result = panel.copy()
    primitives = [
        name
        for name in settings.primitive_factors
        if name in result and result[name].notna().mean() >= 0.50 and name in definitions
    ]
    generated: list[GeneratedFactor] = []

    def add(
        *,
        name: str,
        values: pd.Series,
        directional: bool,
        expression: str,
        operator: str,
        parents: tuple[str, ...],
        window: int | None,
        complexity: int,
    ) -> bool:
        if len(generated) >= settings.max_generated_factors or name in result:
            return False
        result[name] = values.replace([np.inf, -np.inf], np.nan)
        generated.append(
            GeneratedFactor(
                name=name,
                family="discovered_expression",
                directional=directional,
                description=f"Budgeted DSL expression: {expression}",
                expression=expression,
                operator=operator,
                parents=parents,
                window=window,
                complexity=complexity,
                generation_order=len(generated) + 1,
            )
        )
        return True

    if settings.include_cross_sectional_rank and len(generated) < settings.max_generated_factors:
        for primitive in primitives:
            name = f"dsl__cs_rank__{primitive}"
            rank = result.groupby("_feature_time")[primitive].rank(
                method="average", pct=True, na_option="keep"
            )
            add(
                name=name,
                values=2 * rank - 1,
                directional=_definition_direction(definitions, primitive),
                expression=f"cs_rank({primitive})",
                operator="cs_rank",
                parents=(primitive,),
                window=None,
                complexity=1,
            )
            if len(generated) >= settings.max_generated_factors:
                break

    if (
        settings.include_regime_interactions
        and settings.max_complexity >= 2
        and len(generated) < settings.max_generated_factors
    ):
        directional_primitives = [
            name for name in primitives if _definition_direction(definitions, name)
        ]
        regime_primitives = [
            name for name in primitives if not _definition_direction(definitions, name)
        ]
        for directional in directional_primitives:
            for regime in regime_primitives:
                name = f"dsl__interaction__{directional}__{regime}"
                add(
                    name=name,
                    values=result[directional] * result[regime],
                    directional=True,
                    expression=f"multiply({directional},{regime})",
                    operator="multiply",
                    parents=(directional, regime),
                    window=None,
                    complexity=2,
                )
                if len(generated) >= settings.max_generated_factors:
                    break
            if len(generated) >= settings.max_generated_factors:
                break

    if settings.max_complexity >= 1 and len(generated) < settings.max_generated_factors:
        for operator in settings.unary_operators:
            for window in settings.windows:
                for primitive in primitives:
                    directional = (
                        False
                        if operator == "ts_std"
                        else _definition_direction(definitions, primitive)
                    )
                    name = f"dsl__{operator}__{primitive}__{window}"
                    add(
                        name=name,
                        values=_grouped_transform(result, primitive, operator, window),
                        directional=directional,
                        expression=f"{operator}({primitive},{window})",
                        operator=operator,
                        parents=(primitive,),
                        window=window,
                        complexity=1,
                    )
                    if len(generated) >= settings.max_generated_factors:
                        break
                if len(generated) >= settings.max_generated_factors:
                    break
            if len(generated) >= settings.max_generated_factors:
                break
    return result, generated


def generated_catalog(generated: list[GeneratedFactor]) -> pd.DataFrame:
    return pd.DataFrame([asdict(item) for item in generated])
