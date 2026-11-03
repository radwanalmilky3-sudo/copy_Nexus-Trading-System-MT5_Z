"""Update the development dashboard state without touching trading services."""
from __future__ import annotations
import argparse, json, os, tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "project_audit" / "DASHBOARD_STATE.json"
EVIDENCE = ROOT / "project_audit" / "GIT_EVIDENCE_20261016.json"
FIELDS = ("code", "database", "dashboard", "security", "redis", "ml", "tests", "infra", "audit")
STATUSES = ("pending", "in_progress", "done")
MANIFEST_STATUS_MAP = {
    "not verif": "pending",
    "unverified": "pending",
    "not fixed": "pending",
    "not done": "pending",
    "fixed": "done",
    "verif": "done",
    "done": "done",
    "progress": "in_progress",
    "inspected": "pending",
    "reviewed": "pending",
    "implemented": "pending",
    "needs repair": "pending",
}
VERIFIED_NOTE = "fixed+verified 2026-10-16"
SCHEMA_KEYS = ("id", "name", "description", "parent_id", "status", "notes", "start_time", "end_time",
               *FIELDS, "error", "fix", "is_current")

def map_manifest_status(raw: str) -> tuple[str, str]:
    """Map a FILE_MANIFEST.tsv status onto the pending/in_progress/done vocabulary.

    Returns (canonical_status, raw_status). raw_status is non-empty only when the
    manifest value was unknown; the caller must preserve it in the item notes.
    """
    text = (raw or "").strip().lower()
    for keyword, status in MANIFEST_STATUS_MAP.items():
        if keyword in text:
            return status, ""
    return "pending", (raw or "").strip()

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--task")
    p.add_argument("--sync-manifest", action="store_true")
    p.add_argument("--report", action="store_true", help="print status distribution and exit without writing")
    p.add_argument("--rollup-only", action="store_true", help="recompute parent metrics from direct children only")
    p.add_argument("--null-pending-metrics", action="store_true", help="null all metrics+error of pending file:* items")
    p.add_argument("--null-file-metrics", action="store_true", help="null metrics+error of ALL file:* items (scores live on parents only)")
    p.add_argument("--fix-file-placeholders", action="store_true", help="replace generic file:* descriptions with manifest notes or null")
    p.add_argument("--apply-corrections", metavar="PATH", help="apply a corrections JSON file atomically")
    for f in FIELDS:
        if f == "dashboard":
            p.add_argument("--dashboard", "--ui", dest="dashboard", type=int)
        elif f == "infra":
            p.add_argument("--infra", "--infrastructure", dest="infra", type=int)
        else:
            p.add_argument(f"--{f}", dest=f, type=int)
    p.add_argument("--status")
    p.add_argument("--note", default="")
    p.add_argument("--start", dest="start_time")
    p.add_argument("--end", dest="end_time")
    a = p.parse_args()
    data = json.loads(STATE.read_text(encoding="utf-8"))
    _migrate(data)
    if a.report:
        _report(data)
        return 0
    if a.rollup_only:
        parents, changes = _rollup_only(data)
        print(f"rollup-only: {parents} parent(s), {changes} metric(s) updated")
        if changes:
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
            _write(data)
        return 0
    if a.null_pending_metrics:
        n_items, n_fields = _null_pending_metrics(data)
        print(f"null-pending-metrics: {n_items} item(s) nulled, {n_fields} field(s) set to null")
        if n_items:
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
            _write(data)
        return 0
    if a.null_file_metrics:
        n_items, n_fields = _null_file_metrics(data)
        print(f"null-file-metrics: {n_items} item(s) nulled, {n_fields} field(s) set to null")
        if n_items:
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
            _write(data)
        return 0
    if a.fix_file_placeholders:
        n_items, n_nulls, n_notes = _fix_file_placeholders(data)
        print(f"fix-file-placeholders: {n_items} item(s) fixed, {n_nulls} description(s) nulled, {n_notes} replaced from manifest")
        if n_items:
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
            _write(data)
        return 0
    if a.apply_corrections:
        applied, skipped = _apply_corrections(data, Path(a.apply_corrections))
        print(f"apply-corrections: applied={applied} skipped={skipped}")
        if applied:
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
            _write(data)
        return 0
    if a.sync_manifest:
        manifest = ROOT / "project_audit" / "FILE_MANIFEST.tsv"
        existing = {x["id"] for x in data["items"]}
        parents = {x["name"]: x["id"] for x in data["items"] if x.get("parent_id") is None}
        for raw_row in manifest.read_text(encoding="utf-8").splitlines():
            parts = raw_row.split("\t", 2)
            if len(parts) != 3: continue
            file_name, manifest_status, note = parts
            normalized = file_name.replace("\\", "/")
            if not normalized.strip(): continue
            status, unknown_status = map_manifest_status(manifest_status)
            if unknown_status:
                tag = f"manifest status: {unknown_status}"
                note = f"{note}; {tag}" if note.strip() else tag
            segments = normalized.split("/")
            top = segments[0]
            parent_id = parents.get(top, "infrastructure")
            if top == "services" and len(segments) > 1:
                service_id = segments[1].replace("_", "-")
                parent_id = parents.get(service_id, "infrastructure")
            elif top == "dashboard":
                parent_id = parents.get("Frontend application", "infrastructure")
            item_id = "file:" + normalized
            if item_id in existing:
                current_item = next(x for x in data["items"] if x["id"] == item_id)
                current_item["parent_id"] = parent_id
                current_item["status"] = status
                current_item["description"] = note or status
                current_item["notes"] = note
                continue
            data["items"].append({"id": item_id, "name": normalized, "description": note or status, "parent_id": parent_id, "status": status, "notes": note, "start_time": None, "end_time": None, "code": None, "database": None, "dashboard": None, "security": None, "redis": None, "ml": None, "tests": None, "infra": None, "audit": None})
            existing.add(item_id)
        _apply_evidence(data)
        _rollup(data)
        data["last_updated"] = datetime.now(timezone.utc).isoformat()
        data["current_task"] = "متابعة كل ملفات FILE_MANIFEST.tsv"
        _write(data)
        return 0
    if not a.task: raise SystemExit("--task or --sync-manifest is required")
    row = next((x for x in data["items"] if x["id"] == a.task), None)
    if row is None: raise SystemExit(f"Unknown task: {a.task}")
    if a.status and a.status not in STATUSES:
        raise SystemExit(f"Invalid --status {a.status!r}; allowed: {', '.join(STATUSES)}")
    for f in FIELDS:
        value = getattr(a, f)
        if value is not None and not 0 <= value <= 100: raise SystemExit(f"{f} must be 0..100")
        if value is not None: row[f] = value
    if a.status: row["status"] = a.status
    if a.note: row["notes"] = a.note
    if a.start_time: row["start_time"] = a.start_time
    if a.end_time: row["end_time"] = a.end_time
    if a.status == "in_progress" and not row.get("start_time"):
        row["start_time"] = datetime.now(timezone.utc).isoformat()
    if a.status == "done" and not row.get("end_time"):
        row["end_time"] = datetime.now(timezone.utc).isoformat()
    data["current_task"] = {"id": row["id"], "name": row["name"]}
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    _write(data)
    return 0

def _migrate(data: dict) -> None:
    for item in data.get("items", []):
        if "ui" in item:
            if "dashboard" not in item: item["dashboard"] = item["ui"]
            del item["ui"]
        if "infrastructure" in item:
            if "infra" not in item: item["infra"] = item["infrastructure"]
            del item["infrastructure"]

def _report(data: dict) -> None:
    items = data.get("items", [])
    counts = Counter(x.get("status") or "(none)" for x in items)
    total = sum(counts.values())
    print(f"Status distribution ({total} items, last_updated={data.get('last_updated')}):")
    for status, n in counts.most_common():
        pct = (100.0 * n / total) if total else 0.0
        print(f"  {status:<15} {n:>5}  ({pct:5.1f}%)")

def _evidence_paths(payload) -> list[str]:
    out: list[str] = []
    def _looks_like_path(v: str) -> bool:
        return "/" in v or "\\" in v or "." in v
    def _walk(node, depth: int) -> None:
        if depth > 8: return
        if isinstance(node, str):
            if _looks_like_path(node): out.append(node)
        elif isinstance(node, list):
            for x in node: _walk(x, depth + 1)
        elif isinstance(node, dict):
            for key in ("file", "path", "name", "id"):
                v = node.get(key)
                if isinstance(v, str) and _looks_like_path(v):
                    out.append(v)
                    return
            for v in node.values(): _walk(v, depth + 1)
    _walk(payload, 0)
    return out

def _apply_evidence(data: dict) -> None:
    if not EVIDENCE.exists(): return
    try:
        payload = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read {EVIDENCE.name}: {exc}")
    by_id = {x["id"]: x for x in data["items"]}
    for raw_path in _evidence_paths(payload):
        norm = raw_path.replace("\\", "/")
        if norm.startswith("./"): norm = norm[2:]
        if norm.startswith("file:"): norm = norm[5:]
        item = by_id.get("file:" + norm)
        if item is None: continue
        item["status"] = "done"
        note = item.get("notes") or ""
        if VERIFIED_NOTE not in note:
            item["notes"] = f"{note}; {VERIFIED_NOTE}" if note else VERIFIED_NOTE
        if not item.get("end_time"):
            item["end_time"] = datetime.now(timezone.utc).isoformat()

def _rollup(data: dict) -> None:
    items = data.get("items", [])
    children: dict[str, list[dict]] = {}
    for it in items:
        pid = it.get("parent_id")
        if pid: children.setdefault(pid, []).append(it)
    for it in items:
        kids = children.get(it.get("id"))
        if not kids: continue
        for f in FIELDS:
            vals = [k[f] for k in kids if isinstance(k.get(f), (int, float)) and not isinstance(k.get(f), bool)]
            if vals: it[f] = int(sum(vals) / len(vals) + 0.5)

def _children_map(items: list[dict]) -> dict[str, list[dict]]:
    children: dict[str, list[dict]] = {}
    for it in items:
        pid = it.get("parent_id")
        if pid: children.setdefault(pid, []).append(it)
    return children

def _mean_half_up(vals: list) -> int:
    return int(sum(vals) / len(vals) + 0.5)

def _rollup_only(data: dict) -> tuple[int, int]:
    """Recompute parent metrics from DIRECT children only.

    A column whose children are all null/absent keeps the parent's stored value.
    Returns (parents_processed, metrics_updated).
    """
    items = data.get("items", [])
    children = _children_map(items)
    parents = 0
    changes = 0
    for it in items:
        kids = children.get(it.get("id"))
        if not kids: continue
        parents += 1
        parts: list[str] = []
        for f in FIELDS:
            vals = [k.get(f) for k in kids if _is_num(k.get(f))]
            if not vals:
                parts.append(f"{f} kept {it.get(f)!r} (0/{len(kids)} non-null)")
                continue
            new = _mean_half_up(vals)
            if it.get(f) != new:
                parts.append(f"{f} {it.get(f)!r}->{new} ({len(vals)}/{len(kids)} non-null)")
                it[f] = new
                changes += 1
        print(f"  {it.get('id')} ({len(kids)} children): " + ("; ".join(parts) if parts else "unchanged"))
    return parents, changes

def _null_pending_metrics(data: dict) -> tuple[int, int]:
    """Null the 9 metric columns + error for pending items whose id starts with file:."""
    cols = FIELDS + ("error",)
    n_items = 0
    n_fields = 0
    for it in data.get("items", []):
        if it.get("status") != "pending": continue
        if not str(it.get("id") or "").startswith("file:"): continue
        touched = 0
        for c in cols:
            if it.get(c) is not None:
                it[c] = None
                touched += 1
        if touched:
            n_items += 1
            n_fields += touched
    return n_items, n_fields

def _null_file_metrics(data: dict) -> tuple[int, int]:
    """Null the 9 metric columns + error for ALL items whose id starts with file:.

    File-level rows track binary status + textual evidence only; dimension
    scores are curated on parent rows so uniform seed values cannot pollute rollup.
    """
    cols = FIELDS + ("error",)
    n_items = 0
    n_fields = 0
    for it in data.get("items", []):
        if not str(it.get("id") or "").startswith("file:"): continue
        touched = 0
        for c in cols:
            if it.get(c) is not None:
                it[c] = None
                touched += 1
        if touched:
            n_items += 1
            n_fields += touched
    return n_items, n_fields

def _fix_file_placeholders(data: dict) -> tuple[int, int, int]:
    """Replace generic file:* descriptions (parent name, path tokens) with the
    FILE_MANIFEST.tsv note when informative, else null. Real audit text is kept."""
    notes_by_path: dict[str, str] = {}
    manifest = ROOT / "project_audit" / "FILE_MANIFEST.tsv"
    if manifest.exists():
        for raw in manifest.read_text(encoding="utf-8").splitlines():
            parts = raw.split("\t", 2)
            if len(parts) < 2: continue
            path = parts[0].replace("\\", "/").strip()
            note = parts[2].strip() if len(parts) > 2 else ""
            if path and note and len(note) > 15:
                notes_by_path.setdefault(path, note)
    by_id = {x["id"]: x for x in data.get("items", [])}
    n_items = n_nulls = n_notes = 0
    for it in data.get("items", []):
        iid = str(it.get("id") or "")
        if not iid.startswith("file:"): continue
        path = iid[len("file:"):]
        parent_name = ""
        parent = by_id.get(str(it.get("parent_id") or ""))
        if parent: parent_name = str(parent.get("name") or "").strip()
        desc = str(it.get("description") or "").strip()
        tokens = {parent_name, path, path.split("/")[-1], path.split("/")[-1].rsplit(".", 1)[0]}
        tokens.discard("")
        generic = (not desc) or (desc in tokens) or (len(desc) < 12 and desc.lower() in {t.lower() for t in tokens if t})
        if not generic: continue
        replacement = notes_by_path.get(path)
        if replacement and replacement not in tokens:
            it["description"] = replacement
            n_notes += 1
        else:
            it["description"] = None
            n_nulls += 1
        notes = str(it.get("notes") or "").strip()
        if notes == desc and (not it["description"]):
            it["notes"] = None
        n_items += 1
    return n_items, n_nulls, n_notes

def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)

def _validate_fields(values: dict, tag: str) -> list[str]:
    errs: list[str] = []
    for key, val in values.items():
        if key not in SCHEMA_KEYS:
            errs.append(f"{tag}: unknown field {key!r}")
            continue
        if key in FIELDS:
            if val is None: continue
            if not _is_num(val) or not 0 <= val <= 100:
                errs.append(f"{tag}: {key} must be 0..100 or null, got {val!r}")
        elif key == "status":
            if val not in STATUSES:
                errs.append(f"{tag}: status {val!r} not in {', '.join(STATUSES)}")
    return errs

def _apply_corrections(data: dict, path: Path) -> tuple[int, int]:
    """Apply a corrections file: {"operations":[{"id","set","status","notes","reason"},{"add":{...}}]}.

    Everything is validated first; any problem exits 1 listing every bad operation
    without writing. Returns (applied, skipped); re-running is a no-op.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read corrections file {path}: {exc}")
    ops = payload.get("operations") if isinstance(payload, dict) else None
    if not isinstance(ops, list):
        raise SystemExit("Corrections file must be a JSON object with an 'operations' list")
    items = data.setdefault("items", [])
    by_id = {it.get("id"): it for it in items}
    errors: list[str] = []
    for idx, op in enumerate(ops):
        tag = f"operation[{idx}]"
        if not isinstance(op, dict):
            errors.append(f"{tag}: not a JSON object")
            continue
        if "add" in op:
            added = op["add"]
            if not isinstance(added, dict):
                errors.append(f"{tag}: 'add' must be a JSON object")
                continue
            if not isinstance(added.get("id"), str) or not added.get("id"):
                errors.append(f"{tag}: 'add' requires a non-empty string 'id'")
                continue
            errors.extend(_validate_fields(added, f"{tag} add {added['id']}"))
            for key in ("set", "status", "notes"):
                if key in op:
                    errors.append(f"{tag}: 'add' operation cannot also carry '{key}'")
            continue
        iid = op.get("id")
        if not isinstance(iid, str) or not iid:
            errors.append(f"{tag}: missing 'id' (only 'add' operations may omit it)")
            continue
        if iid not in by_id:
            errors.append(f"{tag}: unknown id {iid!r}")
            continue
        if "reason" in op and not (isinstance(op.get("reason"), str) and op["reason"].strip()):
            errors.append(f"{tag}: 'reason' must be a non-empty string")
        raw_set = op.get("set")
        if raw_set is not None and not isinstance(raw_set, dict):
            errors.append(f"{tag}: 'set' must be a JSON object")
            continue
        merged = dict(raw_set or {})
        for key in ("status", "notes"):
            if key in op: merged[key] = op[key]
        if "id" in merged:
            errors.append(f"{tag}: 'id' cannot be changed by 'set'")
            continue
        errors.extend(_validate_fields(merged, f"{tag} {iid}"))
    if errors:
        print(f"apply-corrections: {len(errors)} invalid operation(s); nothing applied:")
        for line in errors:
            print(f"  - {line}")
        raise SystemExit(1)
    applied = 0
    skipped = 0
    for op in ops:
        if "add" in op:
            added = dict(op["add"])
            iid = added["id"]
            if iid in by_id:
                skipped += 1
                continue
            item = {k: (False if k == "is_current" else None) for k in SCHEMA_KEYS}
            item.update(added)
            items.append(item)
            by_id[iid] = item
            applied += 1
            continue
        row = by_id[op["id"]]
        merged = dict(op.get("set") or {})
        for key in ("status", "notes"):
            if key in op: merged[key] = op[key]
        changed = False
        for key, val in merged.items():
            if row.get(key) != val:
                row[key] = val
                changed = True
        if changed: applied += 1
        else: skipped += 1
    return applied, skipped

def _write(data: dict) -> None:
    fd, temp = tempfile.mkstemp(prefix="DASHBOARD_STATE.", suffix=".tmp", dir=STATE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, STATE)
    finally:
        if os.path.exists(temp): os.unlink(temp)
if __name__ == "__main__": raise SystemExit(main())
