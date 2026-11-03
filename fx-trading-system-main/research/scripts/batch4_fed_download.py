#!/usr/bin/env python3
"""Batch4: Fed IFDP 1100-1450 + NY Fed SR 400-1200 (dense), 12 workers, target +100."""
from __future__ import annotations

import hashlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path("/Users/open/fx-trading-system/research/_pdfs")
FED = ROOT / "_fed"
MANIFEST = ROOT / "DOWNLOAD_MANIFEST.csv"
UA = "fx-research-oa-downloader/1.0 (academic; legal OA only)"
TIMEOUT = 45
MIN_BYTES = 10_000  # >10KB
TARGET_NEW = 100
WORKERS = 12

FED.mkdir(parents=True, exist_ok=True)
_lock = threading.Lock()


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_valid_pdf(path: Path) -> bool:
    try:
        if path.stat().st_size <= MIN_BYTES:
            return False
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
        if m and is_valid_pdf(p):
            out.add(int(m.group(1)))
    return out


def existing_sr() -> set[int]:
    out: set[int] = set()
    for p in FED.glob("nyfed_sr*.pdf"):
        m = re.search(r"sr(\d+)", p.name)
        if m and is_valid_pdf(p):
            out.add(int(m.group(1)))
    return out


def fetch_one(url: str, dest: Path) -> tuple[str, int]:
    if dest.exists() and is_valid_pdf(dest):
        return "exists", dest.stat().st_size
    req = Request(url, headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
    except HTTPError as e:
        return f"http_{e.code}", 0
    except Exception as e:  # noqa: BLE001
        return f"err_{type(e).__name__}", 0

    if len(data) <= MIN_BYTES:
        return "empty", len(data)
    if not data.startswith(b"%PDF-"):
        return "not_pdf", len(data)

    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return "ok", len(data)


def download_job(kind: str, n: int) -> dict:
    if kind == "ifdp":
        url = f"https://www.federalreserve.gov/econres/ifdp/files/ifdp{n}.pdf"
        dest = FED / f"ifdp{n}.pdf"
        slug = f"ifdp{n}"
        source = "fed_ifdp"
    else:
        url = f"https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr{n}.pdf"
        dest = FED / f"nyfed_sr{n}.pdf"
        slug = f"nyfed_sr{n}"
        source = "nyfed_sr"

    status, nbytes = fetch_one(url, dest)
    row = None
    if status == "ok":
        digest = sha256(dest)
        row = f"{slug}|{url}|{dest}|{nbytes}|{digest}|{source}|ok|{ts()}"
    elif status not in ("exists",) and dest.exists() and not is_valid_pdf(dest):
        dest.unlink(missing_ok=True)

    return {"kind": kind, "n": n, "status": status, "bytes": nbytes, "row": row}


def main() -> None:
    have_ifdp = existing_ifdp()
    have_sr = existing_sr()

    ifdp_jobs = [("ifdp", n) for n in range(1100, 1451) if n not in have_ifdp]
    # Odds first (more missing historically), then remaining missing; step-1 densify
    sr_missing = [n for n in range(400, 1201) if n not in have_sr]
    sr_jobs = [("sr", n) for n in sorted(sr_missing, key=lambda x: (x % 2 == 0, x))]
    jobs = ifdp_jobs + sr_jobs

    print(
        f"queue ifdp={len(ifdp_jobs)} sr={len(sr_jobs)} total={len(jobs)} "
        f"target={TARGET_NEW} workers={WORKERS}",
        flush=True,
    )

    stats = {
        "ifdp_ok": 0,
        "ifdp_skip": 0,
        "ifdp_fail": 0,
        "sr_ok": 0,
        "sr_skip": 0,
        "sr_fail": 0,
        "probed": 0,
    }
    details: list[str] = []
    new_rows: list[str] = []
    t0 = time.time()

    job_idx = 0
    pending = set()

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        def submit_more() -> None:
            nonlocal job_idx
            while job_idx < len(jobs) and len(pending) < WORKERS * 2 and len(new_rows) < TARGET_NEW:
                k, n = jobs[job_idx]
                job_idx += 1
                pending.add(ex.submit(download_job, k, n))

        submit_more()
        while pending and len(new_rows) < TARGET_NEW:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                res = fut.result()
                stats["probed"] += 1
                kind = res["kind"]
                status = res["status"]
                prefix = "ifdp" if kind == "ifdp" else "sr"
                if status == "ok":
                    stats[f"{prefix}_ok"] += 1
                    new_rows.append(res["row"])
                    details.append(f"OK {kind} {res['n']} ({res['bytes']} bytes)")
                    print(
                        f"  + {kind}{res['n']} {res['bytes']} "
                        f"(new={len(new_rows)}/{TARGET_NEW})",
                        flush=True,
                    )
                elif status == "exists":
                    stats[f"{prefix}_skip"] += 1
                else:
                    stats[f"{prefix}_fail"] += 1
                    if status not in ("http_404", "empty", "not_pdf") and not str(status).startswith(
                        "http_"
                    ):
                        print(f"  ! {kind}{res['n']} {status}", flush=True)
            if len(new_rows) < TARGET_NEW:
                submit_more()
            else:
                # cancel not-yet-started; let in-flight finish without counting beyond report
                for fut in pending:
                    fut.cancel()
                # drain remaining running
                if pending:
                    done2, _ = wait(pending)
                    for fut in done2:
                        if fut.cancelled():
                            continue
                        try:
                            res = fut.result()
                        except Exception:
                            continue
                        stats["probed"] += 1
                        kind = res["kind"]
                        status = res["status"]
                        prefix = "ifdp" if kind == "ifdp" else "sr"
                        if status == "ok":
                            stats[f"{prefix}_ok"] += 1
                            new_rows.append(res["row"])
                            details.append(f"OK {kind} {res['n']} ({res['bytes']} bytes)")
                            print(
                                f"  + {kind}{res['n']} {res['bytes']} "
                                f"(new={len(new_rows)} inflight)",
                                flush=True,
                            )
                        elif status == "exists":
                            stats[f"{prefix}_skip"] += 1
                        else:
                            stats[f"{prefix}_fail"] += 1
                break

    if new_rows:
        with MANIFEST.open("a", encoding="utf-8") as f:
            for row in new_rows:
                f.write(row + "\n")

    new_total = len(new_rows)
    elapsed = time.time() - t0

    # library counts (may be slow; sample _fed focus + total count)
    lib_pdfs = list(ROOT.rglob("*.pdf"))
    valid_count = 0
    invalid = 0
    for p in lib_pdfs:
        try:
            if is_valid_pdf(p):
                valid_count += 1
            else:
                invalid += 1
        except OSError:
            invalid += 1

    fed_ifdp = len([p for p in FED.glob("ifdp*.pdf") if is_valid_pdf(p)])
    fed_sr = len([p for p in FED.glob("nyfed_sr*.pdf") if is_valid_pdf(p)])

    report = FED / "BATCH4.md"
    report.write_text(
        "\n".join(
            [
                "# BATCH4 Fed IFDP + NY Fed SR Download Report",
                "",
                f"- timestamp_utc: {ts()}",
                f"- new_pdfs_this_batch: **{new_total}** (target +{TARGET_NEW})",
                f"- workers: {WORKERS}",
                f"- elapsed_sec: {elapsed:.1f}",
                f"- probed: {stats['probed']}",
                f"- pass1_ifdp: {stats['ifdp_ok']}",
                f"- pass2_nyfed_sr: {stats['sr_ok']}",
                f"- library_pdf_count_after: **{len(lib_pdfs)}**",
                f"- valid_%PDF_header_gt10kb: **{valid_count}** / {len(lib_pdfs)} (invalid: {invalid})",
                f"- _fed ifdp valid: {fed_ifdp}",
                f"- _fed nyfed_sr valid: {fed_sr}",
                "",
                "## Counts (this batch)",
                "",
                "| source | new ok | skip | fail | notes |",
                "|--------|--------|------|------|-------|",
                f"| Fed IFDP | {stats['ifdp_ok']} | {stats['ifdp_skip']} | {stats['ifdp_fail']} | sequential probe 1100–1450; skip existing valid |",
                f"| NY Fed Staff Reports | {stats['sr_ok']} | {stats['sr_skip']} | {stats['sr_fail']} | sr400–sr1200 step 1 densify (odds first) |",
                "",
                "## Sources / URL patterns",
                "",
                "- Fed IFDP: `https://www.federalreserve.gov/econres/ifdp/files/ifdpN.pdf` → `_fed/ifdpN.pdf`",
                "- NY Fed SR: `https://www.newyorkfed.org/medialibrary/media/research/staff_reports/srN.pdf` → `_fed/nyfed_srN.pdf`",
                "",
                "## Manifest",
                "",
                f"- Appended {len(new_rows)} rows to `{MANIFEST}`",
                "- Columns: slug|url|path|bytes|sha256|source|status|ts",
                f"- MIN_BYTES: {MIN_BYTES} (size > 10KB)",
                "- Verify: `%PDF-` magic header required",
                "",
                "## New files (sample up to 120)",
                *[f"- {d}" for d in details[:120]],
                ("- ..." if len(details) > 120 else ""),
                "",
                "## Notes",
                "",
                "- Skip existing valid PDFs (header + size).",
                "- 404/empty/non-PDF discarded; partial files removed.",
                "- Multi-thread ThreadPoolExecutor workers=12.",
                "- Legal open-access Fed / NY Fed research only.",
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
