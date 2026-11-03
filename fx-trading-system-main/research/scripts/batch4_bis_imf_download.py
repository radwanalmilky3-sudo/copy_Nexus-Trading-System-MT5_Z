#!/usr/bin/env python3
"""Batch4: BIS work papers + IMF FX/CIP/UIP/FXI OA PDFs."""
from __future__ import annotations

import hashlib
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/Users/open/fx-trading-system/research/_pdfs")
BIS = ROOT / "_bis"
IMF = ROOT / "_imf"
MANIFEST = ROOT / "DOWNLOAD_MANIFEST.csv"
UA = "fx-research-oa-downloader/1.0 (academic; legal OA only)"
TIMEOUT = 45
MIN_BYTES = 8_000
TARGET_NEW = 45
SLEEP = 0.15

BIS.mkdir(parents=True, exist_ok=True)
IMF.mkdir(parents=True, exist_ok=True)


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def existing_bis_works() -> set[int]:
    out: set[int] = set()
    for p in BIS.glob("*.pdf"):
        for m in re.finditer(r"work(\d+)", p.name):
            out.add(int(m.group(1)))
    return out


def existing_imf_slugs() -> set[str]:
    return {p.stem for p in IMF.glob("*.pdf")}


def fetch(url: str, dest: Path) -> tuple[str, int]:
    if dest.exists() and dest.stat().st_size >= MIN_BYTES and is_pdf(dest):
        return "exists", dest.stat().st_size
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/pdf,*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        return f"http_{e.code}", 0
    except Exception as e:  # noqa: BLE001
        return f"err_{type(e).__name__}", 0

    if len(data) < MIN_BYTES:
        return "empty", len(data)
    if not data.startswith(b"%PDF-"):
        return "not_pdf", len(data)
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return "ok", len(data)


def append_manifest(rows: list[str]) -> None:
    if not rows:
        return
    with MANIFEST.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(row + "\n")


def try_urls(urls: list[str], dest: Path) -> tuple[str, int, str]:
    last_status = "no_url"
    last_n = 0
    for url in urls:
        status, n = fetch(url, dest)
        if status in ("ok", "exists"):
            return status, n, url
        last_status, last_n = status, n
        time.sleep(SLEEP)
    return last_status, last_n, urls[-1] if urls else ""


def imf_urls(year: int, num: int) -> list[str]:
    y = f"{year}"
    n3 = f"{num:03d}"
    n4 = f"{num:04d}"  # rare
    codes = [f"{y}{n3}", f"{y}{n4}"] if num >= 1000 else [f"{y}{n3}"]
    urls: list[str] = []
    for code in codes:
        urls.extend(
            [
                f"https://www.imf.org/-/media/Files/Publications/WP/{y}/English/wpiea{code}-print-pdf.ashx",
                f"https://www.imf.org/-/media/files/publications/wp/{y}/english/wpiea{code}-print-pdf.pdf",
                f"https://www.imf.org/-/media/Files/Publications/WP/{y}/English/wpiea{code}-source-pdf.ashx",
                f"https://www.imf.org/-/media/files/publications/wp/{y}/english/wpiea{code}-source-pdf.pdf",
                f"https://www.imf.org/-/media/files/publications/wp/{y}/english/wpiea{code}-print-pdf.ashx",
            ]
        )
    # eLibrary issue pack + article
    urls.extend(
        [
            f"https://www.elibrary.imf.org/downloadpdf/view/journals/001/{y}/{n3}/001.{y}.issue-{n3}-en.pdf",
            f"https://www.elibrary.imf.org/downloadpdf/view/journals/001/{y}/{n3}/article-A001-en.pdf",
            f"https://www.elibrary.imf.org/downloadpdf/journals/001/{y}/{n3}/article-A001-en.pdf",
        ]
    )
    return urls


def main() -> None:
    have_bis = existing_bis_works()
    have_imf = existing_imf_slugs()
    new_rows: list[str] = []
    stats = {
        "bis_ok": 0,
        "bis_skip": 0,
        "bis_fail": 0,
        "bis_qtr_ok": 0,
        "imf_ok": 0,
        "imf_skip": 0,
        "imf_fail": 0,
    }
    new_count = 0

    # --- BIS work ranges ---
    work_ids: list[int] = []
    work_ids.extend(range(551, 590))  # 550-589 band missing
    work_ids.extend(range(1310, 1401))  # 1310-1400
    # extra high-value CIP/FX works if missing
    work_ids.extend(
        [
            530,
            734,
            802,
            994,
            1013,
            1264,
            1270,
            1280,
            1290,
            1300,
            1305,
            1315,
            1320,
            1330,
            1340,
            1350,
            1360,
            1370,
            1380,
            1390,
        ]
    )
    # de-dupe preserve order
    seen: set[int] = set()
    ordered: list[int] = []
    for w in work_ids:
        if w not in seen:
            seen.add(w)
            ordered.append(w)

    print(f"BIS candidates: {len(ordered)}; already have works: {len(have_bis)}")
    for w in ordered:
        if new_count >= TARGET_NEW + 15:
            break
        if w in have_bis:
            stats["bis_skip"] += 1
            continue
        slug = f"bis_work{w}"
        dest = BIS / f"{slug}.pdf"
        url = f"https://www.bis.org/publ/work{w}.pdf"
        status, n = fetch(url, dest)
        time.sleep(SLEEP)
        if status == "exists":
            stats["bis_skip"] += 1
            have_bis.add(w)
            continue
        if status == "ok":
            digest = sha256(dest)
            row = f"{slug}|{url}|{dest.relative_to(ROOT)}|{n}|{digest}|bis|ok|{ts()}"
            new_rows.append(row)
            stats["bis_ok"] += 1
            new_count += 1
            have_bis.add(w)
            print(f"OK BIS {slug} {n} bytes")
        else:
            stats["bis_fail"] += 1
            if status not in ("http_404", "empty"):
                print(f"FAIL BIS work{w}: {status}")

    # --- BIS quarterly / special FX OA PDFs ---
    qtr_targets = [
        ("bis_qtr_r_qt1309e_fx", "https://www.bis.org/publ/qtrpdf/r_qt1309e.pdf"),
        ("bis_qtr_r_qt1409e", "https://www.bis.org/publ/qtrpdf/r_qt1409e.pdf"),
        ("bis_qtr_r_qt1509e", "https://www.bis.org/publ/qtrpdf/r_qt1509e.pdf"),
        ("bis_qtr_r_qt1703e", "https://www.bis.org/publ/qtrpdf/r_qt1703e.pdf"),
        ("bis_qtr_r_qt1709e", "https://www.bis.org/publ/qtrpdf/r_qt1709e.pdf"),
        ("bis_qtr_r_qt1803e", "https://www.bis.org/publ/qtrpdf/r_qt1803e.pdf"),
        ("bis_qtr_r_qt1809e", "https://www.bis.org/publ/qtrpdf/r_qt1809e.pdf"),
        ("bis_qtr_r_qt1909e", "https://www.bis.org/publ/qtrpdf/r_qt1909e.pdf"),
        ("bis_qtr_r_qt2003e", "https://www.bis.org/publ/qtrpdf/r_qt2003e.pdf"),
        ("bis_qtr_r_qt2009e", "https://www.bis.org/publ/qtrpdf/r_qt2009e.pdf"),
        ("bis_qtr_r_qt2109e", "https://www.bis.org/publ/qtrpdf/r_qt2109e.pdf"),
        ("bis_qtr_r_qt2203e", "https://www.bis.org/publ/qtrpdf/r_qt2203e.pdf"),
        ("bis_qtr_r_qt2303e", "https://www.bis.org/publ/qtrpdf/r_qt2303e.pdf"),
        ("bis_qtr_r_qt2309e", "https://www.bis.org/publ/qtrpdf/r_qt2309e.pdf"),
        ("bis_qtr_r_qt2403e", "https://www.bis.org/publ/qtrpdf/r_qt2403e.pdf"),
        ("bis_qtr_r_qt2409e", "https://www.bis.org/publ/qtrpdf/r_qt2409e.pdf"),
        ("bis_qtr_r_qt2503e", "https://www.bis.org/publ/qtrpdf/r_qt2503e.pdf"),
        ("bis_qtr_r_qt2509e", "https://www.bis.org/publ/qtrpdf/r_qt2509e.pdf"),
        ("bis_work_cip_related_pap73", "https://www.bis.org/publ/bppdf/bispap73.pdf"),
        ("bis_pap67_fx_settlement", "https://www.bis.org/publ/bppdf/bispap67.pdf"),
        ("bis_pap100_fx", "https://www.bis.org/publ/bppdf/bispap100.pdf"),
        ("bis_pap113_fx", "https://www.bis.org/publ/bppdf/bispap113.pdf"),
        ("bis_cgfs65_fx", "https://www.bis.org/publ/cgfs65.pdf"),
        ("bis_cgfs50_fx", "https://www.bis.org/publ/cgfs50.pdf"),
        ("bis_mktc10_fx_execution", "https://www.bis.org/publ/mktc10.pdf"),
        ("bis_mktc05_fx", "https://www.bis.org/publ/mktc05.pdf"),
    ]
    for slug, url in qtr_targets:
        if new_count >= TARGET_NEW + 25:
            break
        dest = BIS / f"{slug}.pdf"
        if dest.exists() and is_pdf(dest) and dest.stat().st_size >= MIN_BYTES:
            stats["bis_skip"] += 1
            continue
        # also skip if any similar basename already
        status, n = fetch(url, dest)
        time.sleep(SLEEP)
        if status == "ok":
            digest = sha256(dest)
            row = f"{slug}|{url}|{dest.relative_to(ROOT)}|{n}|{digest}|bis|ok|{ts()}"
            new_rows.append(row)
            stats["bis_qtr_ok"] += 1
            new_count += 1
            print(f"OK BIS-QTR {slug} {n} bytes")
        elif status != "exists":
            stats["bis_fail"] += 1

    # --- IMF FX / CIP / UIP / FXI working papers ---
    # (year, num, optional_slug_suffix)
    imf_targets: list[tuple[int, int, str]] = [
        (2019, 14, "cip_macrofinancial"),
        (2019, 34, "exchange_rate"),
        (2019, 169, "cip_hedging_asia"),  # may exist
        (2020, 37, "fx"),
        (2020, 74, "macroprudential"),
        (2020, 90, ""),
        (2020, 130, ""),
        (2021, 32, "fxi_rules"),
        (2021, 58, "fx"),
        (2021, 96, ""),
        (2021, 140, ""),
        (2021, 163, "exchange"),
        (2021, 185, "fx"),
        (2022, 12, "fx"),
        (2022, 58, ""),
        (2022, 90, "fx"),
        (2022, 120, ""),
        (2022, 139, "exchange"),
        (2022, 160, "fx"),
        (2023, 28, "uncovering_cip_em"),
        (2023, 42, "fx"),
        (2023, 61, "fxi"),  # may be policy paper path different
        (2023, 80, "exchange"),
        (2023, 100, ""),
        (2023, 120, "fx"),
        (2023, 140, "fx"),
        (2023, 180, "exchange"),
        (2023, 200, "fx"),
        (2024, 15, "fx"),
        (2024, 30, "exchange"),
        (2024, 50, ""),
        (2024, 70, "fx"),
        (2024, 90, "exchange"),
        (2024, 100, "fx"),
        (2024, 120, ""),
        (2024, 150, "fx"),
        (2024, 180, "exchange"),
        (2025, 10, "fx"),
        (2025, 20, "exchange"),
        (2025, 40, "fx"),
        (2025, 57, "cip_em"),
        (2025, 80, "fx"),
        (2025, 100, "exchange"),
        (2025, 120, "fx"),
        (2025, 140, "exchange"),
        (2025, 153, "breaking_parity"),
        (2025, 171, "payment_frictions_fx"),
        (2025, 200, "fx"),
        (2025, 220, "exchange"),
        (2025, 240, "fx"),
        (2025, 261, "optimal_fxi"),
        (2026, 10, "fx"),
        (2026, 20, "exchange"),
        (2026, 40, "fx"),
        (2026, 56, "stablecoin_fx"),
        # older classic FX
        (2018, 10, "fx"),
        (2018, 50, "exchange"),
        (2018, 80, "fx"),
        (2018, 100, "exchange"),
        (2018, 150, "fx"),
        (2017, 30, "fx"),
        (2017, 60, "exchange"),
        (2017, 100, "fx"),
        (2017, 140, "exchange"),
        (2016, 20, "fx"),
        (2016, 60, "exchange"),
        (2016, 100, "fx"),
        (2015, 40, "fx"),
        (2015, 80, "exchange"),
        (2015, 120, "fx"),
        (2014, 30, "fx"),
        (2014, 80, "exchange"),
        (2013, 40, "fx"),
        (2013, 90, "exchange"),
        (2012, 50, "fx"),
        (2011, 40, "exchange"),
        (2010, 30, "fx"),
        (2009, 50, "exchange"),
        (2008, 40, "fx"),
        (2007, 30, "exchange"),
        (2006, 40, "fx"),
        (2005, 50, "exchange"),
        (2004, 40, "fx"),
        (2003, 50, "exchange"),
        (2002, 40, "fx"),
        (2001, 50, "exchange"),
        (2000, 47, "fx"),
    ]

    print(f"IMF candidates: {len(imf_targets)}; existing IMF files: {len(have_imf)}")
    for year, num, suffix in imf_targets:
        if new_count >= TARGET_NEW + 30:
            break
        base = f"imf_wp{year}_{num:03d}"
        slug = f"{base}_{suffix}" if suffix else base
        # skip if any close slug already present
        if any(
            s == slug
            or s.startswith(base)
            or s == f"imf_elibrary_wp{str(year)[2:]}{num:03d}"
            or s == f"imf_elibrary_wp{year}{num:03d}"
            for s in have_imf
        ):
            # more precise: check year_num pattern
            pass
        # Check existing by year/num in filenames
        already = False
        pat = re.compile(rf"(wp{year}_{num:03d}|wp{year}{num:03d}|{year}/{num:03d}|{year}_{num:03d}|{str(year)[2:]}{num:03d})", re.I)
        for name in have_imf:
            if pat.search(name) or name == slug or name.startswith(base):
                already = True
                break
        # special known existences
        if year == 2019 and num == 169:
            already = True
        if year == 2023 and num == 28:
            already = True
        if year == 2025 and num in (57, 153, 171, 261):
            already = True
        if year == 2026 and num == 56:
            already = True
        if year == 2000 and num == 47:
            already = True
        if already:
            stats["imf_skip"] += 1
            continue

        dest = IMF / f"{slug}.pdf"
        urls = imf_urls(year, num)
        status, n, used = try_urls(urls, dest)
        if status in ("ok", "exists"):
            if status == "exists":
                stats["imf_skip"] += 1
                have_imf.add(slug)
                continue
            digest = sha256(dest)
            row = f"{slug}|{used}|{dest.relative_to(ROOT)}|{n}|{digest}|imf|ok|{ts()}"
            new_rows.append(row)
            stats["imf_ok"] += 1
            new_count += 1
            have_imf.add(slug)
            print(f"OK IMF {slug} {n} bytes via {used}")
        else:
            stats["imf_fail"] += 1
            # keep going; many numbers don't exist

    append_manifest(new_rows)
    total_pdfs = sum(1 for _ in ROOT.rglob("*.pdf"))
    print("---")
    print(f"stats={stats}")
    print(f"new_rows={len(new_rows)} new_count={new_count}")
    print(f"library_total_pdfs={total_pdfs}")
    print(f"manifest_appended={len(new_rows)}")


if __name__ == "__main__":
    main()
