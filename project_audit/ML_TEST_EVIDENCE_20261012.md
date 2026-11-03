# ML test evidence — 2026-10-12

Command executed from the project root:

```text
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_ml
```

Result: **17 passed**, exit code 0, 121.81 seconds.

`-p no:cacheprovider` avoided pytest cache writes under the protected project tree. Inspection of the two ML test files shows coverage is timeframe-selection behavior, expected-file presence, and ensemble importability. There are no tests here for training labels/timestamps, true outer walk-forward scoring, model candidate acceptance, rollback, or synthetic-vs-real training-data provenance. Thus these 17 passes do not validate or refute `ML_REVIEW_20261012.md` findings.

No model training, model artifact loading, live Redis/DB access, or trading action occurred during this test run.

## Fresh rerun — 2026-10-14

Command: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_ml`

Result at that point: **17 passed in 6.26 seconds**, exit code 0. This was before the temporal-label regression suite was added.

## Next-bar alignment and outer-fold evaluation regressions — 2026-10-14

- Targeted command: `.venv\Scripts\python.exe -m pytest tests/test_ml -q` — **21 passed in 6.31 seconds**.
- Full command after the risk-state, versioned-history, UTC timestamp, and outer-fold scoring changes: `.venv\Scripts\python.exe -m pytest -q` — **313 passed, 2 deprecation warnings, 142.94 seconds**.
- New cases establish target alignment to the following close, reject equal/older timestamps without shifting pending state, restore pending state after JSON serialization (restart simulation), ensure training reads v2 rather than legacy history, and normalize UTC timestamps without NumPy timezone warnings.
- No live Redis/DB, MT5, model training/artifact loading, or trading action occurred. A Redis server integration/restart test remains unrun.
- `test_walk_forward_validation.py` verifies training rows contain only dates before the outer validation month and that validation metrics are calculated from deterministic outer predictions rather than internal training metrics. LSTM and anomaly paths are implemented but not exercised with real trained artifacts.
