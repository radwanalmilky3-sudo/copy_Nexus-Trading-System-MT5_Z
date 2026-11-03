# MONETARY_VALIDATION — Paper Fundamental Validation phase

**Domain:** MONETARY · **Date (UTC):** 2026-10-10 ~10:10Z · **Mode:** PAPER

## Verdict

```text
MONETARY INGESTION        PASS (Fed RSS live, HTTP 200, recurring ~5-min polls,
                                20 real events with full provenance)
MONETARY ENGINE           PASS (factor conf 73.5 / coverage 100 / freshness 100
                                at 12:42+03 cycle; fusion weight 0.44 latest)
HONESTY                  PASS (non-statement Fed notices → tone 0.0, conf 45 —
                                no invented hawkish/dovish signal; no rate
                                decision in window is stated, not simulated)
```

## Real source & provenance (evidence)

- **fed_rss** — `https://www.federalreserve.gov/feeds/press_all.xml` (REAL official Federal Reserve Board RSS), trust 100, storage allowed, poll 300 s.
- Live `source_health_history` (recurring): `fed_rss|healthy|fresh|code=200|lat 1402–3696 ms|المصدر يعمل وتم جلب بيانات حقيقية.`
- `fund_events` latest-100 slice: **20 fed_rss events** (`FED_COMMUNICATION` ×17, `FOMC` ×3), each with `published_at` (source time, e.g. 2026-09-04T18:00+03), `received_at` (2026-10-10T12:40:27+03 — ingestion time, latencies recorded), `declared_impact`, `gold_relevance=85`, `freshness_state=fresh`, `raw_hash`, `causal_group_id`, `independence_group`.
- Sample real titles: "Federal Reserve Board announces termination of enforcement actions with United Texas Bank…", "Agencies reduce regulatory burden for community banks…", "Agencies seek comment on proposed third-party risk management guidance…".
- `central_bank_events` (20 rows): `institution=Federal Reserve`, `event_kind=FED_COMMUNICATION|FOMC`, with `tone_score=0.0`, `hawkish/dovish_probability=null`, `gold_implication=-0.0`, `confidence=45.0` — the tone engine correctly declines to invent a monetary-policy stance from regulatory notices.

## Engine evidence

- Factor cycle 12:42:30+03: `monetary native/gold score with confidence=73.5, coverage_score=100, freshness_score=100, horizon_class=tactical`.
- Latest fusion (13:04:31+03): `monetary_score=0.0, monetary_weight=0.4398`, minority cluster; Arabic weight reason: «الوزن الأساسي 0.23، الحداثة 1.00، الجودة 0.85، الملاءمة 0.20، الموثوقية 0.45، معامل النظام 1.00، والاستقلال 1.00.» — freshness/quality push the weight up, low gold-fit of regulatory notices pulls it down.
- No FOMC **rate decision** occurred inside the observation window; the engine reflects actual communications only (FOMC-tagged calendar/announcement items), it does not fabricate a decision event.

## API / UI

- Domain served through `GET :9000/api/fundamental/{domain}` (monetary included in the FundamentalWorkspace tab «التحليل الأساسي»).
- Blackout path: monetary events feed `fundamental_blackout_windows` evaluation — currently 0 rows, Redis `nexus:fundamental:blackout` = clear («لا توجد نافذة حظر نشطة»).

```text
MONETARY DOMAIN VALIDATION: PASS (real Fed source, honest stance handling, live fusion weight)
```
