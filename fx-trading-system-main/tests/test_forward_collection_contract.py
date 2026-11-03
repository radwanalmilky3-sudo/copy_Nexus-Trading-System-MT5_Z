from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from fx_system.forward_collection_contract import (
    ForwardCollectionConfig,
    ForwardGenerationManifest,
    assert_forward_generation_eligible,
)

CONFIG = Path(__file__).parents[1] / "configs" / "dukascopy_forward_collection.yaml"


def _generation(start: datetime) -> ForwardGenerationManifest:
    return ForwardGenerationManifest(
        generation_id="20260724T000000Z",
        created_at=datetime(2026, 7, 24, 1, tzinfo=UTC),
        observation_start=start,
        observation_end_exclusive=datetime(2026, 7, 25, tzinfo=UTC),
        source_manifest_sha256="a" * 64,
        immutable=True,
        historical_database_modified=False,
    )


def test_project_forward_config_is_blocked_until_a_real_alpha_freeze() -> None:
    config = ForwardCollectionConfig.from_yaml(CONFIG)
    assert config.status == "blocked_until_alpha_freeze"
    assert config.alpha_freeze_time is None
    assert config.market_history_previously_inspected_through.isoformat() == "2026-07-13"
    with pytest.raises(ValueError, match="not frozen"):
        assert_forward_generation_eligible(config, _generation(datetime(2026, 7, 24, tzinfo=UTC)))


def test_forward_range_must_be_strictly_after_freeze() -> None:
    config = ForwardCollectionConfig.from_yaml(CONFIG).model_copy(
        update={
            "status": "collecting",
            "alpha_freeze_time": datetime(2026, 7, 23, tzinfo=UTC),
        }
    )
    assert_forward_generation_eligible(config, _generation(datetime(2026, 7, 24, tzinfo=UTC)))
    with pytest.raises(ValueError, match="strictly after"):
        assert_forward_generation_eligible(config, _generation(datetime(2026, 7, 23, tzinfo=UTC)))
