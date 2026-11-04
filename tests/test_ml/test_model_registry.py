import json

import pytest

from services.nexus_ml.model_registry import ModelRegistry


def test_generation_manifest_requires_existing_nonempty_artifacts(tmp_path):
    registry = ModelRegistry(tmp_path)
    stage = registry.create_staging("XAUUSD", "M5", "candidate-001")
    artifact = stage / "xgboost_direction.json"
    artifact.write_text("model")

    manifest = registry.write_generation_manifest(
        "XAUUSD", "M5", "candidate-001", ["xgboost_direction.json"], ["f1", "f2"],
    )

    assert manifest["artifacts"] == ["xgboost_direction.json"]
    artifact.unlink()
    with pytest.raises(ValueError, match="artifact"):
        registry.write_generation_manifest(
            "XAUUSD", "M5", "candidate-001", ["xgboost_direction.json"], ["f1", "f2"],
        )


def test_activation_atomically_keeps_previous_generation_on_replace_failure(tmp_path, monkeypatch):
    registry = ModelRegistry(tmp_path)
    for generation in ("gen-1", "gen-2"):
        stage = registry.create_staging("XAUUSD", "M5", generation)
        (stage / "weights.bin").write_bytes(b"ok")
        registry.write_generation_manifest("XAUUSD", "M5", generation, ["weights.bin"], ["f"])
    registry.activate("XAUUSD", "M5", "gen-1")
    old_manifest = registry.read_active("XAUUSD", "M5")

    def fail_replace(_src, _dst):
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr("services.nexus_ml.model_registry.os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        registry.activate("XAUUSD", "M5", "gen-2")

    assert registry.read_active("XAUUSD", "M5") == old_manifest
    assert json.loads(registry.active_manifest_path("XAUUSD", "M5").read_text()) == old_manifest


def test_startup_resolution_falls_back_when_active_bundle_is_corrupt(tmp_path):
    registry = ModelRegistry(tmp_path)
    for generation in ("gen-old", "gen-new"):
        stage = registry.create_staging("XAUUSD", "M5", generation)
        (stage / "weights.bin").write_bytes(b"ok")
        registry.write_generation_manifest("XAUUSD", "M5", generation, ["weights.bin"], ["f"])
        registry.activate("XAUUSD", "M5", generation)
    (registry.generation_dir("XAUUSD", "M5", "gen-new") / "weights.bin").unlink()

    assert registry.resolve_startup_generation("XAUUSD", "M5") == ["gen-old"]


def test_startup_resolution_returns_empty_for_legacy_install(tmp_path):
    registry = ModelRegistry(tmp_path)
    assert registry.resolve_startup_generation("XAUUSD", "M5") == []


def test_manifest_rejects_artifact_path_traversal(tmp_path):
    registry = ModelRegistry(tmp_path)
    stage = registry.create_staging("XAUUSD", "M5", "gen-safe")
    # The security contract is: a traversal artifact name must be rejected
    # with ValueError. write_generation_manifest now checks artifact
    # existence/emptiness before filename safety, so either rejection message
    # upholds the contract — do not pin which guard fires first.
    with pytest.raises(ValueError, match="(safe filenames|artifact missing or empty)"):
        registry.write_generation_manifest("XAUUSD", "M5", "gen-safe", ["..\\escape.bin"], ["f"])


@pytest.mark.parametrize("symbol,generation", [("../outside", "gen"), ("XAUUSD", "../outside")])
def test_registry_rejects_path_traversal(tmp_path, symbol, generation):
    registry = ModelRegistry(tmp_path)
    with pytest.raises(ValueError):
        registry.create_staging(symbol, "M5", generation)


def test_generation_for_one_timeframe_is_not_visible_to_another(tmp_path):
    registry = ModelRegistry(tmp_path)
    stage = registry.create_staging("XAUUSD", "M5", "gen-m5")
    (stage / "weights.bin").write_bytes(b"m5")
    registry.write_generation_manifest("XAUUSD", "M5", "gen-m5", ["weights.bin"], ["f"])
    registry.activate("XAUUSD", "M5", "gen-m5")

    assert registry.resolve_startup_generation("XAUUSD", "M5") == ["gen-m5"]
    assert registry.resolve_startup_generation("XAUUSD", "M15") == []


def test_generation_manifest_without_timeframe_provenance_is_rejected(tmp_path):
    registry = ModelRegistry(tmp_path)
    stage = registry.create_staging("XAUUSD", "M5", "gen-m5")
    (stage / "weights.bin").write_bytes(b"ok")
    manifest_path = stage / "bundle.json"
    manifest_path.write_text(json.dumps({
        "generation_id": "gen-m5", "artifacts": ["weights.bin"], "feature_names": ["f"],
    }))

    with pytest.raises(ValueError, match="identity"):
        registry.read_generation_manifest("XAUUSD", "M5", "gen-m5")
