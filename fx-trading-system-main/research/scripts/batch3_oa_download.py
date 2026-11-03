#!/usr/bin/env python3
"""Batch3 OA PDF bulk downloader: Fed IFDP, NY Fed SR, ECB WP."""
from __future__ import annotations

import hashlib
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/Users/open/fx-trading-system/research/_pdfs")
FED = ROOT / "_fed"
ECB = ROOT / "_ecb"
MANIFEST = ROOT / "DOWNLOAD_MANIFEST.csv"
UA = "fx-research-oa-downloader/1.0 (academic; legal OA only)"
TIMEOUT = 45
MIN_BYTES = 8_000
TARGET_NEW = 70  # aim above 50

FED.mkdir(parents=True, exist_ok=True)
ECB.mkdir(parents=True, exist_ok=True)


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


def existing_ifdp() -> set[int]:
    out: set[int] = set()
    for p in FED.glob("ifdp*.pdf"):
        m = re.search(r"ifdp(\d+)", p.name)
        if m:
            out.add(int(m.group(1)))
    return out


def existing_sr() -> set[int]:
    out: set[int] = set()
    for p in FED.glob("nyfed_sr*.pdf"):
        m = re.search(r"sr(\d+)", p.name)
        if m:
            out.add(int(m.group(1)))
    return out


def existing_ecb() -> set[int]:
    out: set[int] = set()
    for p in ECB.glob("*.pdf"):
        m = re.search(r"wp0*(\d+)", p.name)
        if m:
            out.add(int(m.group(1)))
    return out


def fetch(url: str, dest: Path) -> tuple[str, int]:
    """Return (status, bytes). status in ok|not_pdf|http_error|empty|exists."""
    if dest.exists() and dest.stat().st_size >= MIN_BYTES and is_pdf(dest):
        return "exists", dest.stat().st_size
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").lower()
    except urllib.error.HTTPError as e:
        return f"http_{e.code}", 0
    except Exception as e:  # noqa: BLE001
        return f"err_{type(e).__name__}", 0

    if len(data) < MIN_BYTES:
        return "empty", len(data)
    if not data.startswith(b"%PDF-"):
        # sometimes servers mislabel; still reject non-PDF
        return "not_pdf", len(data)
    # optional ctype check is soft
    _ = ctype
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


def main() -> None:
    have_ifdp = existing_ifdp()
    have_sr = existing_sr()
    have_ecb = existing_ecb()
    new_rows: list[str] = []
    stats = {
        "ifdp_ok": 0,
        "ifdp_skip": 0,
        "ifdp_fail": 0,
        "sr_ok": 0,
        "sr_skip": 0,
        "sr_fail": 0,
        "ecb_ok": 0,
        "ecb_skip": 0,
        "ecb_fail": 0,
    }
    new_total = 0
    details: list[str] = []

    # 1) Fed IFDP sequential 1100-1430
    print("=== IFDP 1100-1430 ===", flush=True)
    for n in range(1100, 1431):
        if new_total >= TARGET_NEW:
            break
        if n in have_ifdp:
            stats["ifdp_skip"] += 1
            continue
        # also skip if any ifdpN*.pdf exists with that number
        existing = list(FED.glob(f"ifdp{n}*.pdf"))
        if existing:
            have_ifdp.add(n)
            stats["ifdp_skip"] += 1
            continue
        url = f"https://www.federalreserve.gov/econres/ifdp/files/ifdp{n}.pdf"
        dest = FED / f"ifdp{n}.pdf"
        status, nbytes = fetch(url, dest)
        if status == "ok":
            digest = sha256(dest)
            slug = f"ifdp{n}"
            row = f"{slug}|{url}|{dest}|{nbytes}|{digest}|fed_ifdp|ok|{ts()}"
            new_rows.append(row)
            stats["ifdp_ok"] += 1
            new_total += 1
            have_ifdp.add(n)
            details.append(f"OK IFDP {n} ({nbytes} bytes)")
            print(f"  + ifdp{n} {nbytes}", flush=True)
        elif status == "exists":
            stats["ifdp_skip"] += 1
            have_ifdp.add(n)
        else:
            stats["ifdp_fail"] += 1
            if dest.exists():
                dest.unlink(missing_ok=True)
            if status not in ("http_404", "empty", "not_pdf") and not status.startswith("http_"):
                print(f"  ! ifdp{n} {status}", flush=True)
        # light politeness
        if n % 25 == 0:
            time.sleep(0.15)

    # 2) NY Fed staff reports sr400-sr1200 step 10
    print("=== NYFed SR 400-1200 step 10 ===", flush=True)
    for n in range(400, 1201, 10):
        if new_total >= TARGET_NEW:
            break
        if n in have_sr:
            stats["sr_skip"] += 1
            continue
        existing = list(FED.glob(f"nyfed_sr{n}*.pdf"))
        if existing:
            have_sr.add(n)
            stats["sr_skip"] += 1
            continue
        url = f"https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr{n}.pdf"
        dest = FED / f"nyfed_sr{n}.pdf"
        status, nbytes = fetch(url, dest)
        if status == "ok":
            digest = sha256(dest)
            slug = f"nyfed_sr{n}"
            row = f"{slug}|{url}|{dest}|{nbytes}|{digest}|nyfed_sr|ok|{ts()}"
            new_rows.append(row)
            stats["sr_ok"] += 1
            new_total += 1
            have_sr.add(n)
            details.append(f"OK NYFed SR {n} ({nbytes} bytes)")
            print(f"  + sr{n} {nbytes}", flush=True)
        elif status == "exists":
            stats["sr_skip"] += 1
            have_sr.add(n)
        else:
            stats["sr_fail"] += 1
            if dest.exists():
                dest.unlink(missing_ok=True)
            print(f"  ! sr{n} {status}", flush=True)
        time.sleep(0.1)

    # 3) ECB working papers — known URL patterns
    # Older style often: ecbwpNNNN.pdf or ecbwpNNNN.en.pdf
    # Mid style: ecb.wpNNNN.en.pdf
    # Newer: hashed ecb.wpNNNN~HASH.en.pdf (need known URLs)
    print("=== ECB WP known patterns ===", flush=True)

    # Candidate numbers not already held, across ranges with high free PDF hit rate
    ecb_candidates: list[int] = []
    # denser sample of older sequential free PDFs
    for n in range(500, 2101, 5):
        if n not in have_ecb:
            ecb_candidates.append(n)
    # extra targeted FX-ish known numbers from literature/search
    extra = [
        548, 600, 700, 750, 800, 850, 900, 1005, 1050, 1100, 1150, 1200,
        1250, 1300, 1350, 1450, 1550, 1600, 1650, 1700, 1800, 1850, 1900,
        1921, 1927, 1950, 2000, 2041, 2050, 2074, 2075, 2100, 2108, 2131,
        2200, 2216, 2250, 2300, 2400, 2450, 2550, 2600, 2630, 2700, 2739,
        2800, 2850, 2900, 2950, 3000, 3020, 3050, 3100, 3150, 3200, 3229,
    ]
    for n in extra:
        if n not in have_ecb and n not in ecb_candidates:
            ecb_candidates.append(n)

    # known direct hashed URLs from search / prior knowledge
    known_urls: dict[int, str] = {
        2041: "https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2041.en.pdf",
        2074: "https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2074.en.pdf",
        2075: "https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp.2075.en.pdf",
        2108: "https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2108.en.pdf",
        2131: "https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2131.en.pdf",
        2216: "https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2216.en.pdf",
        2630: "https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2630~94d9b91ed7.en.pdf",
        2739: "https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2739~7644717754.en.pdf",
        3229: "https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp3229~be05936106.en.pdf",
        548: "https://www.ecb.europa.eu/pub/pdf/scpwps/ecbwp548.pdf",
        1921: "https://www.ecb.europa.eu/pub/pdf/scpwps/ecbwp1921.en.pdf",
        1927: "https://www.ecb.europa.eu/pub/pdf/scpwps/ecbwp1927.en.pdf",
    }

    def ecb_url_candidates(n: int) -> list[str]:
        urls: list[str] = []
        if n in known_urls:
            urls.append(known_urls[n])
        # order by historical likelihood
        urls.extend(
            [
                f"https://www.ecb.europa.eu/pub/pdf/scpwps/ecbwp{n}.pdf",
                f"https://www.ecb.europa.eu/pub/pdf/scpwps/ecbwp{n:03d}.pdf",
                f"https://www.ecb.europa.eu/pub/pdf/scpwps/ecbwp{n}.en.pdf",
                f"https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp{n}.en.pdf",
                f"https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp{n}.pdf",
            ]
        )
        # dedupe preserve order
        seen: set[str] = set()
        out: list[str] = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    # Prefer known first, then sequential older free PDFs
    ordered: list[int] = []
    for n in known_urls:
        if n not in have_ecb:
            ordered.append(n)
    for n in ecb_candidates:
        if n not in ordered:
            ordered.append(n)

    for n in ordered:
        if new_total >= TARGET_NEW:
            break
        if n in have_ecb:
            stats["ecb_skip"] += 1
            continue
        dest = ECB / f"ecb_wp{n}.pdf"
        if dest.exists() and is_pdf(dest) and dest.stat().st_size >= MIN_BYTES:
            stats["ecb_skip"] += 1
            have_ecb.add(n)
            continue
        got = False
        last_status = "none"
        used_url = ""
        for url in ecb_url_candidates(n):
            status, nbytes = fetch(url, dest)
            last_status = status
            if status in ("ok", "exists"):
                used_url = url
                if status == "ok":
                    digest = sha256(dest)
                    slug = f"ecb_wp{n}"
                    row = f"{slug}|{url}|{dest}|{nbytes}|{digest}|ecb_wp|ok|{ts()}"
                    new_rows.append(row)
                    stats["ecb_ok"] += 1
                    new_total += 1
                    have_ecb.add(n)
                    details.append(f"OK ECB WP {n} ({nbytes} bytes)")
                    print(f"  + ecb_wp{n} {nbytes} via {url.split('/')[-1]}", flush=True)
                else:
                    stats["ecb_skip"] += 1
                    have_ecb.add(n)
                got = True
                break
            if dest.exists() and not is_pdf(dest):
                dest.unlink(missing_ok=True)
        if not got:
            stats["ecb_fail"] += 1
            if dest.exists():
                dest.unlink(missing_ok=True)
            # only log non-404 noise sparingly
            if last_status not in ("http_404", "empty", "not_pdf"):
                print(f"  ! ecb_wp{n} {last_status}", flush=True)
        time.sleep(0.05)

    append_manifest(new_rows)

    report = FED / "BATCH3_REPORT.md"
    report.write_text(
        "\n".join(
            [
                "# BATCH3 OA PDF Download Report",
                "",
                f"- timestamp_utc: {ts()}",
                f"- new_pdfs: {new_total}",
                f"- target: +50 (script target {TARGET_NEW})",
                "",
                "## Counts",
                f"- IFDP ok/skip/fail: {stats['ifdp_ok']}/{stats['ifdp_skip']}/{stats['ifdp_fail']}",
                f"- NYFed SR ok/skip/fail: {stats['sr_ok']}/{stats['sr_skip']}/{stats['sr_fail']}",
                f"- ECB WP ok/skip/fail: {stats['ecb_ok']}/{stats['ecb_skip']}/{stats['ecb_fail']}",
                "",
                "## Sources / patterns",
                "- Fed IFDP: `https://www.federalreserve.gov/econres/ifdp/files/ifdpNNNN.pdf` (1100–1430 sequential; keep valid %PDF only)",
                "- NY Fed SR: `https://www.newyorkfed.org/medialibrary/media/research/staff_reports/srN.pdf` (400–1200 step 10)",
                "- ECB WP: `ecbwpN.pdf` / `ecbwpN.en.pdf` / `ecb.wpN.en.pdf` (+ known hashed URLs)",
                "",
                "## Manifest",
                f"- Appended {len(new_rows)} rows to `{MANIFEST}`",
                "- Columns: slug|url|path|bytes|sha256|source|status|ts",
                "",
                "## New files (sample)",
                *[f"- {d}" for d in details[:80]],
                ("- ..." if len(details) > 80 else ""),
                "",
                "## Notes",
                "- All files verified with `%PDF-` magic header before accept.",
                "- 404/empty/non-PDF responses discarded; partial files removed.",
                "- Legal open-access central-bank research only.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print("=== DONE ===", flush=True)
    print(f"new_total={new_total}", flush=True)
    print(stats, flush=True)
    print(f"report={report}", flush=True)


if __name__ == "__main__":
    main()
