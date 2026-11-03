#!/usr/bin/env python3
"""Build L3 PDF index for research/_pdfs (title + abstract extract, no full-text RAG).

ponytail: pypdf first 2 pages only; fail soft on scans; re-run anytime.
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

RESEARCH = Path(__file__).resolve().parents[1]
PDF_ROOT = RESEARCH / "_pdfs"
AGENT = RESEARCH / "agent"
OUT_INDEX = AGENT / "pdf_index.json"
OUT_JSONL = AGENT / "pdf_index.jsonl"
OUT_ABS_DIR = AGENT / "pdf_abstracts"
OUT_STATS = AGENT / "pdf_l3_stats.md"

MAX_PAGES = 2
MAX_TEXT_CHARS = 12000
MAX_ABSTRACT_CHARS = 2500
MAX_TITLE_CHARS = 300
WORKERS = 8

PATH_RE = re.compile(
    r"(?:_pdfs/)?((?:_nber|_bis|_fed|_arxiv|_imf|_ecb|_official|_validation|_micro|_ssrn|02_factor)/[A-Za-z0-9_./\-]+\.pdf)",
    re.I,
)
ID_RE = re.compile(r"\b(w\d{4,5}|work\d{1,4}|ifdp\d{3,4}|wp\d{3,5})\b", re.I)
KEEP_KW = re.compile(
    r"(fx\b|forex|currency|exchange.?rate|carry|cip\b|forward.?bias|uip\b|reer|"
    r"momentum|order.?flow|dealer|wmr|fix|crash|peso|risk.?premi|lustig|verdelhan|"
    r"menkhoff|brunnermeier|koijen|jurek|burnside|itskhoki|factor.?zoo|false.?discovery|"
    r"hansen|spa\b|pbo\b|triennial|rpfx|microstructure|transaction.?cost|bid.?ask|"
    r"variance.?risk|risk.?reversal|cross.?currency|dollar.?funding)",
    re.I,
)


def is_knowledge_doc(p: Path) -> bool:
    if p.suffix.lower() not in {".md", ".json"}:
        return False
    if "_pdfs" in p.parts:
        return "agent" in p.parts
    if p.name.startswith("_BULK") or p.name in {
        "DOWNLOAD_MANIFEST.csv",
        "_PURGE_PLAN.json",
    }:
        return False
    return True


def collect_note_links() -> dict[str, list[str]]:
    """filename/rel -> note paths that mention it."""
    links: dict[str, set[str]] = {}
    for p in RESEARCH.rglob("*"):
        if not p.is_file() or not is_knowledge_doc(p):
            continue
        if p.name in {"pdf_index.json", "catalog.json"} and "agent" in p.parts:
            # still allow routes etc; skip huge generated outputs later
            if p.name == "pdf_index.json":
                continue
        try:
            t = p.read_text(errors="ignore")
        except OSError:
            continue
        rel_note = str(p.relative_to(RESEARCH))
        for m in PATH_RE.findall(t):
            clean = m.split("`")[0].rstrip(".,;")
            key = clean.lower()
            links.setdefault(key, set()).add(rel_note)
            links.setdefault(Path(clean).name.lower(), set()).add(rel_note)
        for m in ID_RE.findall(t):
            links.setdefault(m.lower(), set()).add(rel_note)
    return {k: sorted(v) for k, v in links.items()}


def parse_ids(name: str) -> list[str]:
    ids = set()
    for m in re.findall(r"(w\d{4,5})", name, re.I):
        ids.add(m.lower())
    for m in re.findall(r"work(\d{1,4})\b", name, re.I):
        ids.add("work" + m)
    for m in re.findall(r"ifdp(\d+)", name, re.I):
        ids.add("ifdp" + m)
    for m in re.findall(r"(?:^|_|-)wp(\d{3,5})\b", name, re.I):
        ids.add("wp" + m)
    return sorted(ids)


def clean_text(s: str) -> str:
    s = s.replace("\x00", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def extract_pages(path: Path) -> tuple[str, int, str | None]:
    try:
        reader = PdfReader(str(path), strict=False)
    except Exception as e:  # noqa: BLE001
        return "", 0, f"open_fail:{type(e).__name__}"
    n = len(reader.pages)
    parts: list[str] = []
    err = None
    for i in range(min(MAX_PAGES, n)):
        try:
            parts.append(reader.pages[i].extract_text() or "")
        except Exception as e:  # noqa: BLE001
            err = f"page{i}:{type(e).__name__}"
            break
    text = clean_text("\n".join(parts))[:MAX_TEXT_CHARS]
    if len(text) < 40:
        return text, n, err or "thin_or_scan"
    return text, n, err


def guess_title(text: str, fallback: str) -> str:
    if not text:
        return fallback
    # skip common headers
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    skip = re.compile(
        r"^(nber|national bureau|working paper|federal reserve|bis |ecb |"
        r"international monetary|discussion paper|staff report|wp\s*\d|"
        r"http|www\.|©|copyright|abstract$|keywords?:|jel\s)",
        re.I,
    )
    candidates: list[str] = []
    for ln in lines[:40]:
        if skip.search(ln):
            continue
        if len(ln) < 8 or len(ln) > 220:
            continue
        if re.match(r"^[\d\.\s]+$", ln):
            continue
        # prefer title-ish casing / length
        if re.search(r"[A-Za-z]{4,}", ln):
            candidates.append(ln)
        if len(candidates) >= 5:
            break
    if not candidates:
        return fallback
    # longest early candidate often title; take first long enough
    for c in candidates:
        if len(c) >= 20:
            return c[:MAX_TITLE_CHARS]
    return candidates[0][:MAX_TITLE_CHARS]


def guess_abstract(text: str) -> str:
    if not text:
        return ""
    m = re.search(
        r"(?:^|\n)\s*abstract\s*[:\.]?\s*\n?(.*?)(?:\n\s*(?:1[\.\s]|i[\.\s]|introduction|keywords|jel\b|keywords:))",
        text,
        re.I | re.S,
    )
    if m:
        ab = clean_text(m.group(1))
        return ab[:MAX_ABSTRACT_CHARS]
    # fallback: after title block, take next chunk
    body = text[200:2000] if len(text) > 400 else text
    return clean_text(body)[:800]


def priority_for(rel: str, linked: list[str], name: str) -> str:
    top = rel.split("/")[0] if "/" in rel else "(root)"
    if linked:
        return "hot"
    if top in {"_validation", "_micro", "02_factor", "_ssrn"}:
        return "warm"
    if KEEP_KW.search(name) or KEEP_KW.search(rel):
        return "warm"
    if top == "_official":
        return "warm"
    return "cold"


def process_one(pdf: Path, note_links: dict[str, list[str]]) -> dict:
    rel = pdf.relative_to(PDF_ROOT).as_posix()
    name = pdf.name
    ids = parse_ids(name)
    linked: set[str] = set()
    for key in [rel.lower(), name.lower(), *ids]:
        linked.update(note_links.get(key, []))
    linked_list = sorted(linked)
    text, n_pages, extract_status = extract_pages(pdf)
    title = guess_title(text, fallback=name.replace(".pdf", "").replace("_", " "))
    abstract = guess_abstract(text)
    pr = priority_for(rel, linked_list, name)
    abs_id = re.sub(r"[^\w.\-]+", "_", rel)
    rec = {
        "path": f"_pdfs/{rel}",
        "rel": rel,
        "source": rel.split("/")[0] if "/" in rel else "(root)",
        "ids": ids,
        "bytes": pdf.stat().st_size,
        "pages_reported": n_pages,
        "priority": pr,
        "linked_notes": linked_list,
        "title_guess": title,
        "abstract_chars": len(abstract),
        "extract_status": extract_status or ("ok" if abstract or len(text) > 80 else "empty"),
        "text_chars": len(text),
        "abstract_file": f"agent/pdf_abstracts/{abs_id}.txt" if abstract or text else None,
        "tags_guess": sorted(
            {
                t
                for t, pat in [
                    ("carry", r"carry"),
                    ("cip", r"\bcip\b|covered interest"),
                    ("momentum", r"momentum"),
                    ("fx", r"\bfx\b|foreign exchange|currency|exchange rate"),
                    ("validation", r"false discovery|factor zoo|spa|p-hacking|deflated sharpe|pbo"),
                    ("microstructure", r"order flow|fix|wmr|microstructure|dealer"),
                    ("volatility", r"volatil|risk reversal|variance risk"),
                ]
                if re.search(pat, (title + " " + abstract + " " + name), re.I)
            }
        ),
    }
    # write abstract sidecar
    if rec["abstract_file"]:
        outp = RESEARCH / rec["abstract_file"]
        outp.parent.mkdir(parents=True, exist_ok=True)
        body = (
            f"path: {rec['path']}\n"
            f"title_guess: {title}\n"
            f"ids: {', '.join(ids)}\n"
            f"priority: {pr}\n"
            f"extract_status: {rec['extract_status']}\n"
            f"---\n"
            f"{abstract or text[:MAX_ABSTRACT_CHARS]}\n"
        )
        outp.write_text(body, encoding="utf-8")
    return rec


def main() -> int:
    pdfs = sorted(PDF_ROOT.rglob("*.pdf"))
    print(f"pdfs={len(pdfs)} root={PDF_ROOT}", flush=True)
    note_links = collect_note_links()
    print(f"note_link_keys={len(note_links)}", flush=True)

    records: list[dict] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(process_one, p, note_links): p for p in pdfs}
        done = 0
        for fut in as_completed(futs):
            rec = fut.result()
            records.append(rec)
            done += 1
            if done % 50 == 0 or done == len(pdfs):
                print(f"progress {done}/{len(pdfs)}", flush=True)

    records.sort(key=lambda r: r["rel"])
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "name": "research-pdf-l3-index",
        "level": "L3",
        "updated": stamp,
        "policy": "first_2_pages_title_abstract; no fulltext embeddings",
        "pdf_count": len(records),
        "records": records,
    }
    OUT_INDEX.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with OUT_JSONL.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # stats
    from collections import Counter

    by_pr = Counter(r["priority"] for r in records)
    by_src = Counter(r["source"] for r in records)
    by_st = Counter(r["extract_status"] for r in records)
    thin = sum(1 for r in records if r["text_chars"] < 80)
    linked = sum(1 for r in records if r["linked_notes"])
    stats = f"""# PDF L3 索引统计

生成：`{stamp}`
脚本：`scripts/build_pdf_l3_index.py`
范围：当前磁盘 `_pdfs/**/*.pdf`（**{len(records)}**）

## 文件

| 文件 | 用途 |
|---|---|
| `agent/pdf_index.json` | 全量记录（机器） |
| `agent/pdf_index.jsonl` | 一行一条（流式过滤） |
| `agent/pdf_abstracts/*.txt` | 标题+摘要摘录 sidecar |

## 优先级

| priority | n | 含义 |
|---|---:|---|
| hot | {by_pr.get("hot", 0)} | 知识文档有反链 |
| warm | {by_pr.get("warm", 0)} | 精选目录或 FX 关键词 |
| cold | {by_pr.get("cold", 0)} | 仅库存（保留集内仍可能偏学术） |

## 抽取状态

| status | n |
|---|---:|
{chr(10).join(f"| {k} | {v} |" for k, v in sorted(by_st.items(), key=lambda x: -x[1]))}

- 文本过薄（`<80` chars，多为扫描/坏提取）：**{thin}**
- 至少一篇笔记/文档反链：**{linked}**

## 分目录

| source | n |
|---|---:|
{chr(10).join(f"| `{k}` | {v} |" for k, v in sorted(by_src.items()))}

## Agent 用法

1. 笔记 / `routes.json` 优先
2. 需要搜 PDF：读 `pdf_index.jsonl`，按 `tags_guess` / `title_guess` / `ids` / `priority` 过滤
3. 命中后读对应 `abstract_file`（短）
4. 仍不够再开 **一个** 原 PDF 首页；核 `MISLABEL_LOG`
5. **禁止**把全部 abstracts 一次塞进上下文（按查询 top-k）

## 限制

- `title_guess` / abstract 由首页启发式抽取，**非**出版元数据
- 扫描件、双栏、公式页可能 `thin_or_scan`
- 不做向量库；不做 8000 冷库恢复
"""
    OUT_STATS.write_text(stats, encoding="utf-8")
    print(
        f"wrote {OUT_INDEX} {OUT_JSONL} abstracts={len(list(OUT_ABS_DIR.glob('*.txt')))} "
        f"hot={by_pr.get('hot',0)} warm={by_pr.get('warm',0)} cold={by_pr.get('cold',0)} thin={thin}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
