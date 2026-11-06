#!/usr/bin/env python3
"""T-027 تحقق حي: شارة الإصدار + سعر الذهب الحي في رأس الداشبورد."""
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:3100"
OUT = REPO / "qa" / "evidence" / "t027"
OUT.mkdir(parents=True, exist_ok=True)

load_dotenv(REPO / ".env")
PASSWORD = os.getenv("NEXUS_ADMIN_PASSWORD", "")
assert PASSWORD

results = []


def record(name: str, ok: bool, detail: str) -> None:
    results.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        page.goto(BASE + "/login", wait_until="load", timeout=45000)
        page.fill("form input.neon-input", "redhwan")
        page.fill("input[type=password]", PASSWORD)
        page.click("form button.neon-button")
        page.wait_for_url("**/nexus**", timeout=30000)
        time.sleep(3)

        badge = page.locator('[data-testid="build-badge"]')
        badge_count = badge.count()
        badge_text = badge.first.inner_text() if badge_count else ""
        record("build_badge_visible", badge_count >= 1 and "build:" in badge_text,
               f"count={badge_count} text={badge_text!r}")

        gold = page.locator('[data-testid="live-gold-price"]')
        record("live_gold_chip_visible", gold.count() >= 1, f"count={gold.count()}")
        # انتظر حتى دfirst polling (≤6s)
        deadline = time.time() + 12
        text = gold.first.inner_text() if gold.count() else ""
        while time.time() < deadline:
            text = gold.first.inner_text() if gold.count() else ""
            if "—" not in text:
                break
            time.sleep(1)
        has_price = "XAUUSD" in text and "—" not in text.replace("XAUUSD", "")
        record("live_gold_price_data", has_price, f"chip={text!r}")

        page.screenshot(path=str(OUT / "t027_header_live.png"))
        record("console_errors_zero", len(errors) == 0, f"errors={len(errors)}: {errors[:2]}")
        browser.close()

    (OUT / "verify_result.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    fails = [r for r in results if r["result"] == "FAIL"]
    print(f"TOTAL: {len(results) - len(fails)}/{len(results)} PASS")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
