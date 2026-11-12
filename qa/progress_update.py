#!/usr/bin/env python
"""QA progress store updater — MASTER PROMPT V4.1.

Isolated QA store (qa/progress/state.json). This NEVER touches the NEXUS
trading DuckDB. The dashboard progress page reads this file via
/api/qa-progress.

Usage examples:
  python qa/progress_update.py phase TEST IN_PROGRESS --note "بدء اختبار الشاشات"
  python qa/progress_update.py screen S03 --name "نظرة عامة" --route /nexus --phase IN_PROGRESS
  python qa/progress_update.py result S03 --pass 12 --fail 1 --blocked 2 --not-tested 0 --na 3 --tests 18
  python qa/progress_update.py issue S03 E07 --severity HIGH --desc "..." --root "..." --fix "..." --status "أُصلحت وتحققت" --evidence qa/evidence/x.png
  python qa/progress_update.py element S03 --eid E01 --name "زر الدخول" --type button --status PASS --evidence qa/evidence/e01.json
  python qa/progress_update.py menu S03 --mid M01 --kind multi --options 8 --status PASS
  python qa/progress_update.py integration S03 --component NewsFeed --channel "GET /api/news" --source redis:news:calendar --result PASS --evidence "..."
  python qa/progress_update.py agent lead --task "..." --screen S03 --status COMPLETED --result "..."
  python qa/progress_update.py timeline "نص الحدث"
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STORE = Path(__file__).parent / "progress" / "state.json"

AR_STATUS = {
    "QUEUED": "في الطابور", "IN_PROGRESS": "جارٍ", "COMPLETED": "مكتمل",
    "BLOCKED": "محظور", "PASS": "ناجح", "FAIL": "فاشل",
    "NOT_TESTED": "غير مختبر", "NOT_APPLICABLE": "لا ينطبق",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load() -> dict:
    return json.loads(STORE.read_text(encoding="utf-8"))


def save(state: dict) -> None:
    state["meta"]["last_update"] = now()
    STORE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def recompute(state: dict) -> None:
    s = state["summary"]
    screens = state["screens"]
    s["screens_total"] = max(s.get("screens_total", 0), len(screens))
    s["work_queued"] = sum(1 for x in screens if x["work_status"] == "QUEUED")
    s["work_in_progress"] = sum(1 for x in screens if x["work_status"] == "IN PROGRESS")
    s["work_completed"] = sum(1 for x in screens if x["work_status"] == "COMPLETED")
    s["work_blocked"] = sum(1 for x in screens if x["work_status"] == "BLOCKED")
    tot = ("pass", "fail", "blocked", "not_tested", "not_applicable")
    for k in tot:
        s[k] = sum(x["results"][k] for x in screens)
    s["tests_executed"] = s["pass"] + s["fail"]
    counts: dict[str, int] = {}
    for i in state["issues"]:
        counts[i["severity"].lower()] = counts.get(i["severity"].lower(), 0) + 1
    for sev in ("critical", "high", "medium", "low", "info"):
        s[f"issues_{sev}"] = counts.get(sev, 0)


def get_screen(state: dict, sid: str, create: bool = True) -> dict:
    if sid == "ALL":  # pseudo-scope for cross-screen issues — not a real screen
        raise KeyError(sid)
    for x in state["screens"]:
        if x["screen_id"] == sid:
            return x
    if not create:
        raise KeyError(sid)
    x = {
        "screen_id": sid, "name": sid, "route": "", "phase": "QUEUED",
        "work_status": "QUEUED", "elements": 0, "menus": 0,
        "results": {"pass": 0, "fail": 0, "blocked": 0, "not_tested": 0, "not_applicable": 0},
        "tests_total": 0, "issues": 0, "updated_at": None, "evidence": "",
    }
    state["screens"].append(x)
    return x


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    ph = sub.add_parser("phase")
    ph.add_argument("phase_id")
    ph.add_argument("status")
    ph.add_argument("--note", default="")
    ph.add_argument("--owner", default="")

    sc = sub.add_parser("screen")
    sc.add_argument("screen_id")
    sc.add_argument("--name", default="")
    sc.add_argument("--route", default="")
    sc.add_argument("--phase", default="")
    sc.add_argument("--work-status", dest="work_status", default="")
    sc.add_argument("--elements", type=int, default=-1)
    sc.add_argument("--menus", type=int, default=-1)
    sc.add_argument("--evidence", default="")

    rs = sub.add_parser("result")
    rs.add_argument("screen_id")
    rs.add_argument("--pass", dest="npass", type=int, default=0)
    rs.add_argument("--fail", type=int, default=0)
    rs.add_argument("--blocked", type=int, default=0)
    rs.add_argument("--not-tested", dest="not_tested", type=int, default=0)
    rs.add_argument("--na", dest="not_applicable", type=int, default=0)
    rs.add_argument("--add", action="store_true", help="add to existing counts instead of replace")

    is_ = sub.add_parser("issue")
    is_.add_argument("screen_id")
    is_.add_argument("element_id")
    is_.add_argument("--severity", required=True, choices=["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"])
    is_.add_argument("--desc", required=True)
    is_.add_argument("--repro", default="")
    is_.add_argument("--root", default="")
    is_.add_argument("--fix", default="")
    is_.add_argument("--retest", default="")
    is_.add_argument("--status", default="مفتوحة")
    is_.add_argument("--evidence", default="")

    el = sub.add_parser("element")
    el.add_argument("screen_id")
    el.add_argument("--eid", required=True)
    el.add_argument("--name", required=True)
    el.add_argument("--type", default="")
    el.add_argument("--component", default="")
    el.add_argument("--status", default="NOT_TESTED")
    el.add_argument("--evidence", default="")

    mn = sub.add_parser("menu")
    mn.add_argument("screen_id")
    mn.add_argument("--mid", required=True)
    mn.add_argument("--name", default="")
    mn.add_argument("--kind", default="single")
    mn.add_argument("--options", type=int, default=0)
    mn.add_argument("--searchable", action="store_true")
    mn.add_argument("--status", default="NOT_TESTED")
    mn.add_argument("--evidence", default="")

    ig = sub.add_parser("integration")
    ig.add_argument("screen_id")
    ig.add_argument("--component", required=True)
    ig.add_argument("--channel", required=True)
    ig.add_argument("--source", default="")
    ig.add_argument("--result", default="NOT_TESTED")
    ig.add_argument("--evidence", default="")

    ag = sub.add_parser("agent")
    ag.add_argument("agent_id")
    ag.add_argument("--task", required=True)
    ag.add_argument("--screen", default="ALL")
    ag.add_argument("--status", default="IN PROGRESS")
    ag.add_argument("--result", default="")

    tl = sub.add_parser("timeline")
    tl.add_argument("event")

    a = p.parse_args()
    state = load()

    if a.cmd == "phase":
        for ph_ in state["phases"]:
            if ph_["id"] == a.phase_id:
                ph_["status"] = a.status
                ph_["status_ar"] = AR_STATUS.get(a.status, a.status)
                ph_["updated_at"] = now()
                if a.note:
                    ph_["note"] = a.note
                if a.owner:
                    ph_["owner"] = a.owner
    elif a.cmd == "screen":
        sc_ = get_screen(state, a.screen_id)
        for k, v in (("name", a.name), ("route", a.route), ("phase", a.phase),
                     ("work_status", a.work_status), ("evidence", a.evidence)):
            if v:
                sc_[k] = v
        if a.elements >= 0:
            sc_["elements"] = a.elements
        if a.menus >= 0:
            sc_["menus"] = a.menus
        sc_["updated_at"] = now()
    elif a.cmd == "result":
        sc_ = get_screen(state, a.screen_id)
        for k, v in (("pass", a.npass), ("fail", a.fail), ("blocked", a.blocked),
                     ("not_tested", a.not_tested), ("not_applicable", a.not_applicable)):
            sc_["results"][k] = (sc_["results"][k] + v) if a.add else v
        sc_["tests_total"] = sum(sc_["results"].values())
        sc_["updated_at"] = now()
    elif a.cmd == "issue":
        n = len(state["issues"]) + 1
        state["issues"].append({
            "issue_id": f"ISS-{n:03d}", "screen_id": a.screen_id, "element_id": a.element_id,
            "severity": a.severity, "desc": a.desc, "repro": a.repro, "root": a.root,
            "fix": a.fix, "retest": a.retest, "status": a.status, "evidence": a.evidence,
            "updated_at": now(),
        })
        try:
            get_screen(state, a.screen_id, create=False)["issues"] = sum(
                1 for i in state["issues"] if i["screen_id"] == a.screen_id)
        except KeyError:
            pass  # cross-screen (ALL) or unknown screen — no single screen counter
    elif a.cmd == "element":
        state["elements"].append({
            "element_id": a.eid, "screen_id": a.screen_id, "name": a.name, "type": a.type,
            "component": a.component, "status": a.status, "status_ar": AR_STATUS.get(a.status, a.status),
            "evidence": a.evidence, "updated_at": now(),
        })
    elif a.cmd == "menu":
        state["menus"].append({
            "menu_id": a.mid, "screen_id": a.screen_id, "name": a.name, "kind": a.kind,
            "options": a.options, "searchable": a.searchable, "status": a.status,
            "status_ar": AR_STATUS.get(a.status, a.status), "evidence": a.evidence, "updated_at": now(),
        })
    elif a.cmd == "integration":
        state["integrations"].append({
            "screen_id": a.screen_id, "component": a.component, "channel": a.channel,
            "source": a.source, "result": a.result, "result_ar": AR_STATUS.get(a.result, a.result),
            "evidence": a.evidence, "updated_at": now(),
        })
    elif a.cmd == "agent":
        entry = None
        for g in state["agents"]:
            if g["agent_id"] == a.agent_id:
                entry = g
                break
        if entry is None:
            entry = {"agent_id": a.agent_id, "role": a.agent_id}
            state["agents"].append(entry)
        entry.update({"task": a.task, "screen": a.screen, "status": a.status,
                      "result": a.result, "updated_at": now()})
    elif a.cmd == "timeline":
        state["timeline"].append({"at": now(), "event": a.event})
        state["timeline"] = state["timeline"][-200:]

    recompute(state)
    save(state)
    print(f"OK {a.cmd} -> {STORE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
