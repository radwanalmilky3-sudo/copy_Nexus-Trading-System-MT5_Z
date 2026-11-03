# SOURCE_HEALTH_ACTUAL — Live Fundamental Source Status

**Sources of truth:**
- `GET http://127.0.0.1:9005/api/news/sentinel/status` (per-source health registry)
- `GET http://127.0.0.1:9005/health` (news/calendar caches, blackout state)
- `GET http://127.0.0.1:9005/api/news/latest` (live news payload)
- nexus-news logs (`calendar_poll_ok`, official source loop)

**Captured:** 2026-10-10, services running in PAPER mode.

## Health summary

| Source | Health | Evidence |
|---|---|---|
| BLS (Bureau of Labor Statistics) | **healthy** | Real fetch, `origin=real`, freshness=fresh, 160/160 records accepted, latency ~2.3 s, last_success current |
| Federal Reserve RSS | **healthy** | Real fetch, `origin=real`, freshness=fresh, 20/20 records accepted, latency ~2.1 s |
| NewsAPI | degraded (stale) | Key present in `.env`; last recorded failure was a transient Redis outage; news cache currently serves **48 articles** |
| GNews | degraded (stale) | Key present in `.env`; same transient outage record; articles present in cache |
| Secondary Economic Calendar | degraded→recovering | 83 calendar events loaded; poll loop verified cycling (`calendar_poll_ok` recurring); blackout state recomputed to `clear` |
| World Bank | unknown | No credentials configured; freshness=degraded |
| BEA | config_required | Needs `BEA_API_KEY` |
| FRED | config_required | Needs `FRED_API_KEY` |
| CFTC COT | config_required | Needs `CFTC_COT_ENDPOINT` |
| U.S. Treasury | config_required | Needs `TREASURY_DATA_ENDPOINT` |
| IMF | config_required | Needs `IMF_DATA_ENDPOINT` |
| Gold ETF Flows | config_required | Needs endpoint config |
| Central-Bank Gold Buying | config_required | Needs endpoint config |
| Market Flow / OI / Volume / Options | config_required | Needs endpoint config |

## Live payload evidence

- `GET /api/news/latest` → **48 articles** (real provider headlines, timestamps within last 24 h, XAU-relevant tagging, FinBERT scores present).
- Calendar cache: **83 events**; poll loop confirms every 300 s.
- Canonical blackout state (Redis `nexus:fundamental:blackout`): `{"state":"clear","active":false,"reason_code":"CLEAR"}` — recomputed by FundamentalRuntime after the last successful calendar scan.

## Explicit unavailable sources (pack rule: unavailable must stay explicit)

Sources marked `config_required` have **no credentials/endpoints configured** on this machine and must remain unavailable rather than mocked. They are declared in `fund_sources` with `auth_type`, `api_key_env`, and license metadata; enabling them is a Phase-2 action (add keys, then the official source loop picks them up without code changes).

## Notes

- Provider health `degraded` entries for NewsAPI/GNews/calendar reference a historical Redis connectivity outage (WSL environment incident, since fixed and documented in `IMPLEMENTATION_REPORT.md` §5). Subsequent fetches succeeded; caches are populated and loops verified alive.
- No mock/live fallback exists in NewsFeed (pack static contract, golden test PASS).
