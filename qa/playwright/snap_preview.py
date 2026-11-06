#!/usr/bin/env python3
"""لقطة معاينة الداشبورد السحابي للمالك — تسجيل دخول صامت ثم لقطتا شاشة.

الاستخدام: venv-nexus/bin/python3 qa/playwright/snap_preview.py
المخرجات: download/cloud_dashboard_login.png + download/cloud_dashboard_overview.png
البيانات: NEXUS_ADMIN_PASSWORD من .env — لا تُطبع أبداً.
"""
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:3100"
OUT = REPO.parent / "download"
OUT.mkdir(exist_ok=True)

load_dotenv(REPO / ".env")
PASSWORD = os.getenv("NEXUS_ADMIN_PASSWORD", "")
if not PASSWORD:
    sys.exit("NEXUS_ADMIN_PASSWORD missing in .env")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE + "/login", wait_until="load", timeout=45000)
        time.sleep(1.5)
        page.screenshot(path=str(OUT / "cloud_dashboard_login.png"))
        page.fill("form input.neon-input", "redhwan")
        page.fill("input[type=password]", PASSWORD)
        page.click("form button.neon-button")
        page.wait_for_url("**/nexus**", timeout=30000)
        time.sleep(4)  # مؤشرات حية
        page.screenshot(path=str(OUT / "cloud_dashboard_overview.png"), full_page=False)
        browser.close()
    for name in ("cloud_dashboard_login.png", "cloud_dashboard_overview.png"):
        f = OUT / name
        print(f"{name}: {f.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
