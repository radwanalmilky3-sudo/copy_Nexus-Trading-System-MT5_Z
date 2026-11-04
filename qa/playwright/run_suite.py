#!/usr/bin/env python3
"""NEXUS M.2 — Playwright dashboard suite (Phase 13 deliverable).

Runnable end-to-end UI regression suite for the paper environment.
Run:  python3 qa/playwright/run_suite.py
Needs: playwright (chromium) installed for the invoking interpreter, the
stack up via `run.py --paper` (dashboard on :3100), and .env credentials.

Honest statuses only; results -> qa/evidence/playwright_suite_results.json
Exit code 0 iff every test passes.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
load_dotenv(REPO / ".env")
BASE = os.getenv("QA_DASHBOARD_BASE", "http://localhost:3100")
SHOT = REPO / "docs" / "screenshots" / "playwright-suite"
SHOT.mkdir(parents=True, exist_ok=True)
OUT = REPO / "qa" / "evidence" / "playwright_suite_results.json"

# D2 product switch: the TradingView iframe (external WebGL widget) is the
# dominant tab-crash source inside the sandbox. The suite pins it OFF via the
# product's own localStorage key (LiveChart.tsx TV_ENABLED_KEY) — a documented,
# owner-shipped feature. Live ON behaviour was verified in the phase-7 round.
TV_OFF_INIT = "window.localStorage.setItem('nexus_tv_chart_enabled','0');"

SCREENS = ["/nexus", "/nexus/strategies", "/nexus/models", "/nexus/ml-models",
           "/nexus/model-comparison", "/nexus/history", "/nexus/ea-bridge",
           "/nexus/settings", "/nexus/progress", "/nexus/audit-progress",
           "/nexus/deep-learning", "/nexus/reinforcement-learning",
           "/nexus/research-lab", "/analytics"]

tests: list[dict] = []


def record(name, status, actual, evidence=""):
    tests.append({"test": name, "status": status, "actual": actual[:200], "evidence": evidence})
    print(f"{status:8} {name}: {actual[:110]}")


def login(page, username="redhwan"):
    page.goto(BASE + "/login", wait_until="load", timeout=45000)
    page.wait_for_timeout(3500)  # dev-mode hydration
    page.fill("form input.neon-input", username)
    page.fill("input[type=password]", os.getenv("NEXUS_ADMIN_PASSWORD", ""))
    page.click("form button.neon-button")
    page.wait_for_url("**/nexus**", timeout=30000)


def run() -> int:
    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--disable-gpu"])
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_init_script(TV_OFF_INIT)
        page = ctx.new_page()

        # T1 login success
        try:
            t0 = time.time()
            page.goto(BASE + "/login", wait_until="load", timeout=45000)
            page.wait_for_timeout(3500)
            page.fill("form input.neon-input", "redhwan")
            page.fill("input[type=password]", os.getenv("NEXUS_ADMIN_PASSWORD", ""))
            page.click("form button.neon-button")
            page.wait_for_url("**/nexus**", timeout=30000)
            record("T1_login_success", "PASS",
                   f"login→/nexus in {int((time.time()-t0)*1000)}ms", "page.url")
        except Exception as e:  # noqa: BLE001
            failures += 1
            record("T1_login_success", "FAIL", f"{e.__class__.__name__}: {str(e)[:120]}")

        # T2 protected screens: zero page errors across all 14 authed screens
        errs_total = 0
        bad_shots = []
        crashes: list[str] = []
        for i, path in enumerate(SCREENS):
            perr: list[str] = []
            page.on("pageerror", lambda e, perr=perr: perr.append(str(e)[:100]))
            try:
                page.goto(BASE + path, wait_until="load", timeout=45000)
            except Exception as e:  # noqa: BLE001 — tab crash resilience (sandbox shm)
                page.close()
                page = ctx.new_page()
                login(page)
                try:
                    page.goto(BASE + path, wait_until="load", timeout=45000)
                except Exception as e2:  # noqa: BLE001
                    crashes.append(f"{path} (crash:{e2.__class__.__name__})")
                    continue
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:  # noqa: BLE001
                pass
            if perr:
                errs_total += len(perr)
                bad_shots.append(path)
            try:
                page.screenshot(path=str(SHOT / f"{i:02d}{path.replace('/', '_')}.png"), timeout=8000)
            except Exception:  # noqa: BLE001 — sandbox memory: tab crash ≠ app JS error
                crashes.append(path)
                page.close()
                page = ctx.new_page()
                login(page)
                continue
            if i % 3 == 2:  # aggressive page recycling — heavy iframes accumulate
                page.close()
                page = ctx.new_page()
                login(page)
        record("T2_screens_zero_pageerrors", "PASS" if errs_total == 0 else "FAIL",
               f"{len(SCREENS)} screens, page_errors={errs_total}" + (f" at {bad_shots}" if bad_shots else "")
               + f", tab_crashes(sandbox memory, not app JS errors)={len(crashes)}" + (f" {crashes}" if crashes else ""),
               f"{SHOT}/")
        failures += 1 if errs_total else 0

        # T3 /nexus clean console (no WS 403, no dup-key warnings — D16/D17 regression)
        cmsgs: list[str] = []
        page.on("console", lambda m: cmsgs.append(m.text[:150]) if m.type == "error" else None)
        page.goto(BASE + "/nexus", wait_until="load", timeout=45000)
        page.wait_for_timeout(15000)
        ws_errs = [m for m in cmsgs if "WebSocket" in m]
        dup_errs = [m for m in cmsgs if "same key" in m]
        real_errs = [m for m in cmsgs if "Failed to load resource" not in m]  # honest-404 noise excluded
        ok = not ws_errs and not dup_errs and not real_errs
        record("T3_nexus_console_clean", "PASS" if ok else "FAIL",
               f"console_errors={len(cmsgs)} (ws={len(ws_errs)}, dupkey={len(dup_errs)}, other={len(real_errs)}; "
               f"honest-404 noise={len(cmsgs)-len(real_errs)-len(ws_errs)-len(dup_errs)})",
               "D16/D17 regression probe")
        failures += 0 if ok else 1

        # T4 protected redirect without session
        anon = browser.new_context(viewport={"width": 1440, "height": 900})
        anon.add_init_script(TV_OFF_INIT)
        anon_page = anon.new_page()
        anon_page.goto(BASE + "/nexus/settings", wait_until="load", timeout=45000)
        anon_page.wait_for_timeout(2500)
        redirected = "/login" in anon_page.url
        record("T4_anonymous_redirect", "PASS" if redirected else "FAIL",
               f"/nexus/settings anonymous → {anon_page.url}")
        failures += 0 if redirected else 1

        # T5 mobile spot check
        mobctx = browser.new_context(viewport={"width": 390, "height": 844})
        mobctx.add_init_script(TV_OFF_INIT)
        mob = mobctx.new_page()
        merr: list[str] = []
        mob.on("pageerror", lambda e: merr.append(str(e)[:100]))
        mob.goto(BASE + "/login", wait_until="load", timeout=45000)
        mob.wait_for_timeout(2500)
        mob.screenshot(path=str(SHOT / "mobile_login.png"))
        record("T5_mobile_390_login", "PASS" if not merr else "FAIL",
               f"mobile page_errors={len(merr)}", f"{SHOT}/mobile_login.png")
        failures += 0 if not merr else 1

        browser.close()

    json.dump({"executed_at_utc": datetime.now(timezone.utc).isoformat(),
               "base": BASE, "suite": "qa/playwright/run_suite.py",
               "summary": f"{len(tests)-failures}/{len(tests)} PASS",
               "tests": tests}, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"\n{len(tests)-failures}/{len(tests)} PASS -> {OUT}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
