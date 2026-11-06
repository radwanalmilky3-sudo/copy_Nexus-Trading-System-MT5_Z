#!/usr/bin/env python3
"""جولة حية مصورة في الداشبورد السحابي — فيديو + لقطات لكل الشاشات.

المخرجات في download/:
  cloud_env_1_login.png    صفحة الدخول
  cloud_env_2_overview.png نظرة عامة بعد الدخول
  cloud_env_3_settings.png شاشة الوسيط والحسابات
  cloud_env_4_eabridge.png شاشة جسر MT5
  cloud_env_5_history.png  سجل الصفقات
  cloud_env_6_analytics.png التحليلات
  cloud_env_tour.webm      فيديو الجولة كاملاً
"""
import time
from pathlib import Path

from dotenv import load_dotenv
import os
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:3100"
OUT = REPO.parent / "download"
OUT.mkdir(exist_ok=True)

load_dotenv(REPO / ".env")
PASSWORD = os.getenv("NEXUS_ADMIN_PASSWORD", "")
assert PASSWORD, "NEXUS_ADMIN_PASSWORD missing"

SHOTS = [
    ("/login", "cloud_env_1_login.png", 2.5),
    ("/nexus", "cloud_env_2_overview.png", 5.0),
    ("/nexus/settings", "cloud_env_3_settings.png", 3.0),
    ("/nexus/ea-bridge", "cloud_env_4_eabridge.png", 3.0),
    ("/history", "cloud_env_5_history.png", 3.0),
    ("/analytics", "cloud_env_6_analytics.png", 3.0),
]


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=str(OUT),
            record_video_size={"width": 1280, "height": 720},
        )
        page = ctx.new_page()

        # 1) صفحة الدخول — نظرة أطول في الفيديو
        page.goto(BASE + "/login", wait_until="load", timeout=45000)
        time.sleep(2.5)
        page.screenshot(path=str(OUT / "cloud_env_1_login.png"))

        # 2) دخول فعلي ببيانات المالك (لا تُطبع)
        page.fill("form input.neon-input", "redhwan")
        page.fill("input[type=password]", PASSWORD)
        page.click("form button.neon-button")
        page.wait_for_url("**/nexus**", timeout=30000)

        # 3..) بقية الشاشات — الأولى نظرة عامة بانتظار المؤشرات الحية
        for path, name, wait in SHOTS[1:]:
            page.goto(BASE + path, wait_until="load", timeout=45000)
            time.sleep(wait)
            page.screenshot(path=str(OUT / name))

        video = page.video
        ctx.close()
        if video:
            vpath = video.path()
            browser.close()
            target = OUT / "cloud_env_tour.webm"
            Path(vpath).rename(target)
            print(f"video: {target.name} {target.stat().st_size} bytes")
        else:
            browser.close()
    for _, name, _ in SHOTS:
        f = OUT / name
        print(f"{name}: {f.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    main()
