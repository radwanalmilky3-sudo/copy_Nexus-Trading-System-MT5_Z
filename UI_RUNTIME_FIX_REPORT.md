# UI_RUNTIME_FIX_REPORT

**Date (UTC):** 2026-10-10 ~11:15Z · **Page:** http://localhost:3100/dashboard · **Mode:** PAPER fleet untouched

## Confirmed root cause (as approved)

```text
D. STALE_NEXT_BUILD   primary — production `npm run build` (07:21–07:23) overwrote the
                      .next directory of the ALREADY-RUNNING `next dev` server (since 05:51),
                      leaving a mixed production+dev build state
G. CACHE_ISSUE        contributing — dev server kept serving HTML whose asset references
                      came from its in-memory dev manifest, no longer matching disk
C. STATIC_ASSET_404   direct symptom — /_next/static/css/app/layout.css?v=… → 404
                      (plus main-app.js?v=, app/dashboard/page.js?v= → 404) ⇒ unstyled HTML
```

## What was done (minimal runtime fix — zero source changes)

| step | action |
|---|---|
| 1 | Evidence preserved: old BUILD_ID `iQCL9UiOuozNhop214WLU`, `.next` manifest snapshot (2051 files; static CSS: `862bc9e25556ca96.css` 43,112 B @07:21) → `next_evidence_before.json` (temp) |
| 2 | Dashboard tree stopped by exact PID (no `taskkill /IM`): **8472** (start-server.js), **6876** (`next dev -p 3100`), **6652** (cmd wrapper), **2928** (launcher) → port **3100 FREE** confirmed |
| 3 | `.next` removed by the project's own official supervisor: run.py's `spawn_dashboard` launcher runs `(if exist .next rmdir /s /q .next) & npm run dev -- --port 3100` — clean dev restart, no other service touched |
| 4 | Watchdog respawned dashboard in ~50 s: new **`next dev` PID 23504** → **start-server PID 5784** (port 3100 owner) |
| 5 | Cold dev compile completed on warm-up request: **200, 166,008 B in 78.7 s** |

## Runtime verification (after)

```text
PAGE                    200 text/html 166,008 B
CSS link (dev)          /_next/static/css/app/layout.css?v=1791631691085
  → HTTP 200, text/css, 62,680 B, contains Tailwind (--tw-/.flex) AND theme vars (--bg-primary)
JS chunks               6/6 → 200
  main-app.js 6,017,491 · app-pages-internals 139,037 · app/dashboard/page.js 7,640,681
  app/dashboard/layout.js 1,002,668 · app/layout.js 359,268 · polyfills.js 91,381
CSS 404s                0 (was: layout.css + 4 JS assets 404 before fix)
MIME errors             0 (all text/css / application/javascript)
HTML markers            class="dark" ✔  bg-matrix ✔  antialiased ✔
inline <style>          0 (normal for dev-mode external stylesheet serving)
```

### Before vs after (network layer)

| asset | before | after |
|---|---|---|
| `css/app/layout.css?v=` | **404** | **200 (62.6 KB, tailwind+theme)** |
| `chunks/main-app.js?v=` | **404** | 200 |
| `chunks/app/dashboard/page.js` | **404** | 200 |
| `chunks/app/layout.js` | 200 | 200 |
| production `css/862bc9e….css` | 200 (orphaned — HTML didn't reference it) | n/a (fresh .next) |

## Console / visual

- Console-error classes guarded against (CSS 404, MIME mismatch, chunk-load failure) are eliminated at the network layer; DevTools automation was not attached in this environment.
- Screenshot automation: the broken-state PNG was overwritten by a straggler headless instance, and post-fix headless captures were blocked by the user's own open Edge session holding the profile (attempts logged). **HTTP-level proof above is conclusive**; the currently open browser tab will show the restored theme on hard refresh (Ctrl+F5). Please confirm visually.

## Untouched (re-verified after fix)

```text
Ports 9000-9008   same PIDs as before (7208/19668/5980/5520/1620/10248/9852/6612/6252)
nexus-api         healthy · nexus-news healthy · nexus-executor broker=paper
Redis / MT5 / Ollama / Python services   not touched
SOURCE FILES MODIFIED = 0   (only build cache dashboard/.next removed + process restart)
```

## Files modified

```text
dashboard/.next     REMOVED (build cache — regenerated fresh by next dev)
<any source file>   NONE
```

## Future rule (adopted)

**Never run `npm run build` while `next dev` is serving the same project/`.next`.** For future production-build validation:
`STOP dashboard dev → npm run build → record result → delete production .next → start clean next dev`
(or use a separate build directory if ever required).

## Final status

```text
UI RUNTIME RESTORED
```
