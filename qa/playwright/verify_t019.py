#!/usr/bin/env python3
"""T-019 live UI verification: unified news screen (single stacked view).

Matches the deployed design (commit 94963e3): the top-level News tab is the
ONLY news screen — live news rows (clickable) + selected-news detail pane +
economic calendar table + active ticker, all in one view above the existing
filters. The duplicated FundamentalWorkspace news section must be gone.
"""
import os, sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]  # qa/playwright/ -> repo root
load_dotenv(REPO / ".env")
BASE = os.getenv("QA_DASHBOARD_BASE", "http://127.0.0.1:3100")


def do_login(page):
    page.goto(BASE + "/login", wait_until="load", timeout=45000)
    page.wait_for_timeout(3500)  # hydration
    page.fill("form input.neon-input", "redhwan")
    page.fill("input[type=password]", os.getenv("NEXUS_ADMIN_PASSWORD", ""))
    page.click("form button.neon-button")
    page.wait_for_url("**/nexus**", timeout=30000)


checks = {}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--disable-gpu"])
    ctx = browser.new_context(viewport={"width": 1600, "height": 900})
    ctx.add_init_script("window.localStorage.setItem('nexus_tv_chart_enabled','0');")
    page = ctx.new_page()
    do_login(page)

    # 1) open the top-level News tab -> the single unified news screen
    page.click("button:has-text('الأخبار (News)')")
    page.wait_for_timeout(2500)
    body = page.inner_text("body")
    checks["unified_title"] = "الشاشة الموحدة" in body
    checks["section_live_news"] = "الأخبار الحقيقية" in body
    checks["section_detail"] = "تفاصيل الخبر المختار" in body
    checks["section_calendar"] = "التقويم الاقتصادي" in body
    checks["section_ticker"] = "الشريط النشط" in body
    checks["filters_bar"] = ("التأثير" in body) and ("الفترة" in body)
    checks["search_box"] = page.get_by_placeholder("بحث في الأخبار").count() >= 1

    # 2) click a news row -> detail pane reacts (or honest empty state)
    rows = page.locator("button:has(h4)")
    if rows.count() > 0:
        rows.first.click()
        page.wait_for_timeout(600)
        checks["detail_reacts"] = "ماذا حدث؟" in page.inner_text("body")
        checks["news_rows_state"] = f"live_rows={rows.count()}"
    else:
        # no live rows right now -> the detail pane must honestly invite selection
        checks["detail_reacts"] = "اختر خبرًا لعرض التفاصيل" in page.inner_text("body")
        checks["news_rows_state"] = "honest_empty"

    page.screenshot(path=str(REPO / "docs" / "screenshots" / "t019_news_center.png"), full_page=False)

    # 3) FundamentalWorkspace must no longer offer the duplicated news section
    page.click("button:has-text('التحليل الأساسي')")
    page.wait_for_timeout(2500)
    fw = page.inner_text("body")
    checks["fw_news_section_removed"] = ("الأخبار والتقويم" not in fw) and ("نظرة عامة على الذهب" in fw)

    browser.close()

ok = all(v for k, v in checks.items() if k != "news_rows_state")
for k, v in checks.items():
    print(f"{'PASS' if v else 'FAIL'} {k}")
passed = sum(1 for k, v in checks.items() if v and k != "news_rows_state")
total = len([k for k in checks if k != "news_rows_state"])
print(f"T019_NEWS_CENTER: {'PASS ' + str(passed) + '/' + str(total) + ' (' + checks['news_rows_state'] + ')' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
