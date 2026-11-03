# UI_ACCEPTANCE — Dashboard Build & Route Acceptance

**App:** `dashboard/` (Next.js) · **Dev port:** 3100 (served by `run.py` fleet)

## Production build

```text
npm run build  →  exit 0
First Load JS shared by all: 87.3 kB
```

Routes built (all static/prerendered unless noted):

| Route | Size | First Load JS |
|---|---|---|
| `/` | 146 B | 87.5 kB |
| `/_not-found` | 875 B | 88.2 kB |
| `/analytics` | 2.29 kB | 97 kB |
| `/dashboard` (main) | 165 kB | 266 kB |
| `/dashboard/deep-learning` | 4.87 kB | 99.6 kB |
| `/dashboard/history` | 5 kB | 99.7 kB |
| `/dashboard/ml-models` | 4.6 kB | 99.3 kB |
| `/dashboard/model-comparison` | 5.81 kB | 100 kB |
| `/dashboard/models` | 6.79 kB | 101 kB |
| `/dashboard/reinforcement-learning` | 5.01 kB | 99.6 kB |
| `/dashboard/settings` | 8.32 kB | 110 kB |
| `/dashboard/strategies` | 8 kB | 105 kB |
| `/history` | 144 B | 87.5 kB |
| `/icon.svg` | 0 B | 0 B |
| `/login` | 3.59 kB | 90.9 kB |
| `/settings` | 146 B | 87.5 kB |

## TypeScript

```text
npx tsc --noEmit  →  exit 0 (no type errors)
```

## Runtime smoke (fleet running, PAPER mode)

| Check | Result |
|---|---|
| `GET http://127.0.0.1:3100/` | **HTTP 200** |
| `GET http://127.0.0.1:3100/dashboard` | **HTTP 200** |
| First hit latency note | initial request slow due to Next.js dev compilation; subsequent requests fast |

## Backend routes consumed by the UI (sample, all green)

| Endpoint | Result |
|---|---|
| `:9000/health` | healthy; redis connected; duckdb connected |
| `:9001/api/data/fundamental/schema` | 27 tables |
| `:9005/api/news/latest` | 48 articles |
| `:9007/health` | broker=paper, trading_mode=paper, real_broker_execution_enabled=false |

## Acceptance statement

The dashboard builds cleanly, typechecks cleanly, and serves both the landing page and the main `/dashboard` view against the live PAPER fleet. No UI change was made beyond what the Golden Pack delivered.
