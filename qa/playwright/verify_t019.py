#!/usr/bin/env python3
"""T-019 live UI verification: unified news center replaces duplicated news tables."""
import os, sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
load_dotenv(REPO / ".env")
BASE = os.getenv("QA_DASHBOARD_BASE", "http://127.0.0.1:3100")


def do_login(page):
    page.goto(BASE + "/login", wait_until="load", timeout=45000)
    page.wait_for_timeout(3500)
    page.fill("form input.neon-input", "redhwan")
    page.fill("input[type=password]", os.getenv("NEXUS_ADMIN_PASSWORD", ""))
    page.click("form button.neon-button")
    page.wait_for_url("**/nexus**", timeout=30000)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--disable-gpu"])
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    do_login(page)

    # 1) open top-level news tab -> unified news center
    page.click("text=الأخبار")
    page.wait_for_timeout(2500)
    body = page.inner_text("body")
    checks = {}
    checks["unified_title"] = "مركز الأخبار الموحد" in body
    checks["tab_live"] = "الأخبار الحية" in body
    checks["tab_calendar"] = "التقويم الاقتصادي" in body
    checks["tab_ticker"] = "الشريط النشط" in body

    # 2) switch to calendar tab, then ticker tab
    page.click("text=التقويم الاقتصادي")
    page.wait_for_timeout(800)
    checks["calendar_tab_opens"] = "الحدث" in page.inner_text("body")
    page.click("text=الشريط النشط")
    page.wait_for_timeout(800)
    checks["ticker_tab_opens"] = "قائمة الشريط النشطة" in page.inner_text("body")

    # 3) fundamental workspace must no longer offer a news tab
    page.click("text=الأساسي")
    page.wait_for_timeout(2500)
    fw = page.inner_text("body")
    checks["fw_no_news_tab"] = ("الأخبار والتقويم" not in fw) and ("نظرة عامة على الذهب" in fw)

    page.screenshot(path=str(REPO / "docs" / "screenshots" / "t019_news_center.png"), full_page=False)
    browser.close()

ok = all(checks.values())
for k, v in checks.items():
    print(f"{'PASS' if v else 'FAIL'} {k}")
print(f"T019_NEWS_CENTER: {'PASS ' + str(sum(checks.values())) + '/' + str(len(checks)) if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
