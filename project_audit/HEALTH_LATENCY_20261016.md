# Health Latency Evidence — 2026-10-16 (read-only collector)

Method: `curl -m 6 -w "%{http_code} %{time_total}"`, 15 sequential samples per port, localhost. p95 = nearest-rank (n=15 ⇒ 15th/max).

| port | n | min (ms) | avg (ms) | max (ms) | p95 (ms) | non-200 |
|---|---|---|---|---|---|---|
| 9000 (api gateway) | 15 | 560 | 744 | 880 | 880 | 0 |
| 9001 | 15 | 3 | 11 | 33 | 33 | 0 |
| 9002 | 15 | 3 | 3 | 4 | 4 | 0 |
| 9003 | 15 | 3 | 8 | 49 | 49 | 0 |
| 9004 | 15 | 3 | 7 | 14 | 14 | 0 |
| 9005 | 15 | 4 | 11 | 27 | 27 | 0 |
| 9006 | 15 | 4 | 15 | 45 | 45 | 0 |
| 9007 | 15 | 3 | 10 | 29 | 29 | 0 |
| 9008 | 15 | 3 | 15 | 50 | 50 | 0 |
| 3100 /api/health (start) | 1 | — | 894 | 894 | 894 | 0 (HTTP 200) |
| 3100 /api/health (end) | 1 | — | 1670 | 1670 | 1670 | 0 (HTTP 200) |

3100 JSON `services[]` (start → end, latencyMs):
- nexus-api: 741 → 1623 (dominates total; consistent with 9000 direct ~0.6–0.9s, occasionally higher)
- nexus-data: 35 → 17; nexus-agents: 20 → 21; nexus-risk: 33 → 31; nexus-executor: 40 → 23; nexus-ml: 34 → 18

## Comparison / 3000ms breaches
- **No port breached 3000ms** in any sample (worst overall: 9000 @ 880ms; 3100 total worst 1670ms).
- **9000 pre-fix: 0/15 samples >3s, but 100% of samples >500ms** — high constant overhead vs <50ms peers; variance within acceptable range (560–880ms, ~1.6x spread) at time of measurement. No non-200 observed.

## Verdict: is a 3s per-service timeout safe?
- **All ports 9001–9008: YES — trivially safe** (p95 ≤ 50ms; 60x+ headroom).
- **9000 (api): YES — safe with ~3.4x headroom on worst observed** (880ms max). Even if post-fix latency drops to peer levels (<50ms), 3s remains safe; if future cold-start spikes appear, 3s still covers the observed envelope.
- **3100 aggregation: YES, but tightly coupled to 9000** — total ≈ sum/parallel-probe of services; observed 0.9–1.7s. A 3s per-service timeout keeps the aggregate well under typical 5s ceilings, but 3100's own client timeout should be ≥ 2× the largest per-service timeout if services are probed sequentially.

## Fixer's context (read-only snapshot)
- `services/nexus_api/main.py` `/health` handler (`health_check`, lines 160–173): **14 lines**. Sequential awaits: `redis.health_check()` + `data_service.health()` with no explicit timeouts; file total 196 lines.
