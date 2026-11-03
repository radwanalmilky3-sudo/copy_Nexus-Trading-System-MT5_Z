# ML Candidate Promotion and Rollback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent automatic ML retraining from replacing a serving ensemble unless a complete candidate generation passes same-fold acceptance checks and can be loaded atomically.

**Architecture:** Train each symbol into a unique staged generation, persist a strict artifact manifest, compare candidate and incumbent on identical outer folds, validate a fresh ensemble, then atomically activate it while retaining the previous generation for rollback. Legacy model directories remain supported as incumbents until first promotion.

**Tech Stack:** Python, pathlib, JSON manifests, same-directory `os.replace`, NumPy/scikit-learn metrics, pytest.

**Spec:** `docs/superpowers/specs/2026-10-14-ml-model-promotion-design.md`

## Global Constraints

- At least 3 valid temporal outer folds are required for promotion.
- Candidate mean outer log-loss must be strictly lower and accuracy must not decline, per model and on identical folds.
- Models without a comparable incumbent are not automatically promoted.
- Model generations are immutable; never train into the active generation or legacy incumbent directory.
- Failed candidate operations leave the current serving ensemble and active manifest unchanged.
- No live MT5, trade execution, production service, live DuckDB, or live Redis operations.

## Review Focus

- Two or fewer valid folds must reject promotion; test exact boundary.
- Equal log-loss must reject while accuracy tie is allowed only when log-loss strictly improves; test both.
- Model targets cannot be mixed; test regime model comparison remains within regime labels.
- Legacy startup and missing active-generation metadata must preserve existing load behavior; test compatibility.
- Atomic activation and failed reload must preserve the previous object and manifest; inject failures at both boundaries.
- Anomaly detector changes alter a signal veto; test preservation of the incumbent artifact only under identical feature schema.

## File Map

- Create `services/nexus_ml/model_registry.py`: generation paths, artifact manifest, active pointer, atomic activation and fallback resolution.
- Modify `services/nexus_ml/training.py`: strict-save option and explicit persistence failures for candidate runs; expose fold data needed for incumbent scoring without changing legacy trainer defaults.
- Modify `services/nexus_ml/main.py`: staged candidate orchestration, same-fold incumbent scoring, candidate validation and activation without evicting the serving ensemble early; status event details.
- Modify `services/nexus_ml/ensemble.py`: strict complete-load validation mode and model path/schema loading for generation bundles while retaining permissive legacy default.
- Create/update `tests/test_ml/test_model_registry.py`, `tests/test_ml/test_model_promotion.py`, and focused trainer/ensemble tests.
- Update `project_audit/COVERAGE.md`, `FILE_MANIFEST.tsv`, and ML audit follow-up with verified results.

### Task 1: Immutable generation registry and atomic active pointer

**Files:** Create `services/nexus_ml/model_registry.py`; test `tests/test_ml/test_model_registry.py`.

**Interfaces:** `ModelRegistry(root: Path)`, `create_staging(symbol: str, generation_id: str) -> Path`, `write_generation_manifest(...)`, `read_active(symbol)`, `activate(symbol, generation_id)`, and `resolve_startup_generation(symbol)`.

- [ ] Test safe generation IDs, unique staging locations, and manifest artifact existence/non-empty checks.
- [ ] Verify tests fail before implementation.
- [ ] Implement registry with atomic same-directory manifest replacement and no deletion of old generations.
- [ ] Inject replace failure and assert previous active manifest remains intact.
- [ ] Run `pytest tests/test_ml/test_model_registry.py -q`.

### Task 2: Strict candidate persistence and full ensemble validation

**Files:** Modify `services/nexus_ml/training.py`, `services/nexus_ml/ensemble.py`; add focused tests.

**Interfaces:** Preserve current defaults; add strict persistence mode for candidate training and a strict load operation that returns success only when every artifact listed in the generation manifest loads and feature schema is valid.

- [ ] Test a model save exception causes strict training to fail while default legacy behavior remains compatible.
- [ ] Test strict ensemble loading rejects missing/corrupt listed artifacts and succeeds on a complete fixture bundle.
- [ ] Implement strict candidate save/validation without altering existing model serialization formats.
- [ ] Run focused trainer/ensemble tests and existing ML model tests.

### Task 3: Comparable same-fold acceptance evaluator

**Files:** Create `services/nexus_ml/model_promotion.py`; test `tests/test_ml/test_model_promotion.py`.

**Interfaces:** `evaluate_promotion(candidate_metrics, incumbent_metrics, min_folds=3) -> PromotionDecision`; return stable reason codes and per-model aggregates. Only compare metrics for identical model key, target labels, fold IDs, and validation row IDs.

- [ ] Test fewer than 3 folds, missing incumbent, target/fold mismatch, log-loss equality, improved loss with tied accuracy, and declined accuracy.
- [ ] Implement strict mean-log-loss/accuracy rule and per-model handling; anomaly statistics are excluded.
- [ ] Run `pytest tests/test_ml/test_model_promotion.py -q`.

### Task 4: Candidate orchestration without serving interruption

**Files:** Modify `services/nexus_ml/main.py`; add orchestration tests.

- [ ] Test rejection, training/save/load failure, and activation failure all preserve the prior cached ensemble object.
- [ ] Test accepted candidate becomes active only after complete load and pointer activation; prior generation remains resolvable.
- [ ] Implement auto-retrain to stage generation, evaluate incumbent and candidate on identical frozen folds, validate fresh ensemble, activate pointer, then atomically replace the in-memory symbol ensemble reference.
- [ ] Preserve existing retrain status fields and add sanitized candidate outcome details.
- [ ] Run focused retraining and API status tests.

### Task 5: Startup compatibility, audit evidence, and regression suite

**Files:** Modify startup model resolution and audit docs/manifest; add startup tests.

- [ ] Test active generation startup, corrupted-active fallback to retained previous generation, and legacy-directory startup.
- [ ] Implement resolution according to the spec without rewriting legacy artifacts.
- [ ] Run focused ML tests, then full suite: `pytest -q`.
- [ ] Record actual command outputs, update coverage/manifest statuses, and document any unresolved limitations. Do not claim complete project audit; broader coverage remains outstanding.

## Execution Notes

There is no `.git` directory in the current project workspace, so do not create commits or claim Git-based rollback. Preserve all current workspace files and use the retained legacy/previous model generation strategy for runtime rollback.
