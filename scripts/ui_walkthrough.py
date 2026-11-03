"""Headless Edge (CDP) dashboard walkthrough — remediation plan items 250/251.

Visits the dashboard routes/tabs in report-unit order, screenshots each stop
with UTC stamps, and captures console output, HTTP responses, and WebSocket
frames through the DevTools Protocol (no HAR dependency). Evidence lands in
project_audit/remediation-20261021/.

Usage:
  .venv/Scripts/python.exe scripts/ui_walkthrough.py [--base http://127.0.0.1:3100]
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "project_audit" / "remediation-20261021"
SHOTS = OUT / "screenshots"
EVID = OUT / "evidence"
TOKEN_FILE = Path(os.environ.get("TEMP", ".")) / "nexus-restart" / "walkthrough_token.txt"
EDGE_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]
CDP_PORT = 9444
VIEW_W, VIEW_H = 1440, 2000
REDACT: list[str] = []

# Report-unit coverage per step (plan "تغطية الوحدات الـ52").
STEPS: list[dict] = [
    {"units": "52", "name": "login-unauthenticated", "url": "/login", "settle": 3.0},
    {"units": "1", "name": "overview", "url": "/dashboard", "settle": 5.0},
    {"units": "2", "name": "positions", "url": "/dashboard", "click": "Positions", "settle": 4.0},
    {"units": "3", "name": "risk", "url": "/dashboard", "click": "Risk", "settle": 4.0},
    {"units": "4,7-14", "name": "news", "url": "/dashboard", "click": "News", "settle": 4.0},
    {"units": "5,18", "name": "agents", "url": "/dashboard", "click": "Agents", "settle": 4.0},
    {"units": "6", "name": "intelligence", "url": "/dashboard", "click": "Intelligence", "settle": 4.0},
    {"units": "7-14", "name": "fundamental", "url": "/dashboard", "click": "التحليل الأساسي", "settle": 5.0},
    {"units": "16", "name": "journal", "url": "/dashboard", "click": "Journal", "settle": 4.0},
    {"units": "17", "name": "backtest", "url": "/dashboard", "click": "Backtest", "settle": 4.0},
    {"units": "18", "name": "console", "url": "/dashboard", "click": "Console", "settle": 4.0},
    {"units": "19", "name": "strategies", "url": "/dashboard/strategies", "settle": 5.0},
    {"units": "20-24", "name": "models", "url": "/dashboard/models", "settle": 5.0},
    {"units": "20-24", "name": "model-comparison", "url": "/dashboard/model-comparison", "settle": 5.0},
    {"units": "25", "name": "history", "url": "/dashboard/history", "settle": 5.0},
    {"units": "26", "name": "settings-trading", "url": "/dashboard/settings", "settle": 5.0},
    {"units": "26", "name": "settings-risk", "url": "/dashboard/settings", "settle": 5.0},
    {"units": "26", "name": "settings-signals", "url": "/dashboard/settings", "click": "Señales", "settle": 3.0},
    {"units": "26", "name": "settings-models", "url": "/dashboard/settings", "click": "Modelos", "settle": 3.0},
    {"units": "33-37", "name": "settings-notifications", "url": "/dashboard/settings", "click": "Notificaciones", "expect_text": "Notif. navegador", "settle": 3.0},
    {"units": "33-37", "name": "settings-lower", "url": "/dashboard/settings", "scroll": "bottom", "settle": 3.0},
    {"units": "27-31", "name": "settings-broker-panel", "url": "/dashboard/settings", "scroll": "bottom", "settle": 3.0, "shot": "full"},
    {"units": "38", "name": "progress", "url": "/dashboard/progress", "settle": 5.0},
    {"units": "39", "name": "rlab-datasets", "url": "/dashboard/research-lab", "settle": 5.0},
    {"units": "40", "name": "rlab-cleaning", "url": "/dashboard/research-lab", "click": "التنظيف", "settle": 3.5},
    {"units": "41", "name": "rlab-validation", "url": "/dashboard/research-lab", "click": "التحقق", "settle": 3.5},
    {"units": "42", "name": "rlab-provenance", "url": "/dashboard/research-lab", "click": "التتبّع", "settle": 3.5},
    {"units": "43", "name": "rlab-strategies", "url": "/dashboard/research-lab", "click": "الاستراتيجيات", "settle": 3.5},
    {"units": "44", "name": "rlab-backtests", "url": "/dashboard/research-lab", "click": "الاختبارات التاريخية", "settle": 3.5},
    {"units": "45", "name": "rlab-news", "url": "/dashboard/research-lab", "click": "الأخبار", "settle": 3.5},
    {"units": "46", "name": "rlab-artifacts", "url": "/dashboard/research-lab", "click": "المخرجات", "settle": 3.5},
    {"units": "47", "name": "audit-progress", "url": "/dashboard/audit-progress", "settle": 5.0},
    {"units": "48", "name": "deep-learning", "url": "/dashboard/deep-learning", "settle": 5.0},
    {"units": "49", "name": "ml-models", "url": "/dashboard/ml-models", "settle": 5.0},
    {"units": "50", "name": "reinforcement-learning", "url": "/dashboard/reinforcement-learning", "settle": 5.0},
    {"units": "1,51", "name": "analytics", "url": "/analytics", "settle": 4.0},
    {"units": "51", "name": "root-redirect", "url": "/", "settle": 3.0},
    {"units": "51", "name": "shared-notifications", "url": "/dashboard", "click": "bell", "settle": 4.0},
]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def file_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def find_edge() -> Path:
    for p in EDGE_CANDIDATES:
        if p.exists():
            return p
    raise SystemExit("msedge.exe not found")


def launch_edge(profile: Path) -> subprocess.Popen:
    kill_stale_edge()
    edge = find_edge()
    args = [
        str(edge),
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={profile}",
        f"--window-size={VIEW_W},{VIEW_H}",
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--hide-scrollbars",
        "about:blank",
    ]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kill_stale_edge() -> None:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
             "Where-Object { $_.CommandLine -like '*remote-debugging-port=9444*' -or $_.CommandLine -like '*nexus-walk-profile*' } | "
             "Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=15,
        )
        for pid in filter(None, (p.strip() for p in out.stdout.splitlines())):
            if pid.isdigit():
                subprocess.run(["taskkill", "/T", "/F", "/PID", pid],
                               capture_output=True, timeout=10)
    except Exception:
        pass


def stop_edge(proc: subprocess.Popen) -> None:
    try:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True, timeout=10)
    except Exception:
        pass
    try:
        proc.terminate()
    except Exception:
        pass


def cdp_list() -> list[dict]:
    with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=3) as resp:
        return json.loads(resp.read().decode())


class Recorder:
    def __init__(self) -> None:
        self.step = "startup"
        self.console: list[dict] = []
        self.http: list[dict] = []
        self.failures: list[dict] = []
        self.ws: list[dict] = []
        self.ws_frames: dict[str, dict] = {}
        self.per_step: dict[str, dict] = {}

    def bucket(self) -> dict:
        return self.per_step.setdefault(
            self.step,
            {"console_errors": 0, "http_4xx": 0, "http_5xx": 0, "failed_requests": 0, "ws_urls": set()},
        )

    def event(self, method: str, params: dict) -> None:
        ts = utc_stamp()
        b = self.bucket()
        if method == "Runtime.consoleAPICalled":
            if params.get("type") in ("error", "warning"):
                text = " ".join(
                    str(a.get("value", a.get("description", "")))[:300]
                    for a in params.get("args", [])
                )
                self.console.append({"step": self.step, "ts": ts, "level": params["type"], "text": text})
                if params["type"] == "error":
                    b["console_errors"] += 1
        elif method == "Runtime.exceptionThrown":
            detail = params.get("exceptionDetails", {})
            self.console.append(
                {
                    "step": self.step,
                    "ts": ts,
                    "level": "exception",
                    "text": str(detail.get("text", ""))[:300],
                    "stack": str(detail.get("exception", {}).get("description", ""))[:500],
                }
            )
            b["console_errors"] += 1
        elif method == "Network.responseReceived":
            info = params.get("response", {})
            status = int(info.get("status", 0) or 0)
            self.http.append(
                {
                    "step": self.step,
                    "ts": ts,
                    "type": params.get("type", ""),
                    "status": status,
                    "url": info.get("url", "")[:500],
                }
            )
            if 400 <= status < 500:
                b["http_4xx"] += 1
            elif status >= 500:
                b["http_5xx"] += 1
        elif method == "Network.loadingFailed":
            self.failures.append(
                {
                    "step": self.step,
                    "ts": ts,
                    "error": params.get("errorText", ""),
                    "canceled": params.get("canceled", False),
                    "type": params.get("type", ""),
                }
            )
            b["failed_requests"] += 1
        elif method == "Network.webSocketCreated":
            url = params.get("url", "")[:300]
            for s in REDACT:
                url = url.replace(s, "[REDACTED]")
            self.ws.append({"step": self.step, "ts": ts, "event": "created", "url": url})
            b["ws_urls"].add(url.split("?")[0])
            self.ws_frames.setdefault(params.get("requestId", ""), {"sent": 0, "received": 0, "samples": []})
        elif method in ("Network.webSocketFrameSent", "Network.webSocketFrameReceived"):
            direction = "sent" if method.endswith("Sent") else "received"
            bucket = self.ws_frames.setdefault(params.get("requestId", ""), {"sent": 0, "received": 0, "samples": []})
            bucket[direction] += 1
            payload = str(params.get("response", {}).get("payloadData", ""))[:200]
            for s in REDACT:
                payload = payload.replace(s, "[REDACTED]")
            if len(bucket["samples"]) < 6 and payload:
                bucket["samples"].append({"dir": direction, "ts": ts, "payload": payload})


class CDP:
    def __init__(self, ws_url: str, rec: Recorder) -> None:
        self.ws_url = ws_url
        self.rec = rec
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._ws = None
        self._reader_task = None

    async def connect(self) -> None:
        self._ws = await websockets.connect(self.ws_url, max_size=64 * 1024 * 1024, open_timeout=15)
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if "id" in msg and msg["id"] in self._pending:
                    fut = self._pending.pop(msg["id"])
                    if not fut.done():
                        fut.set_result(msg)
                elif "method" in msg:
                    try:
                        self.rec.event(msg["method"], msg.get("params", {}))
                    except Exception:
                        pass
        except websockets.ConnectionClosed:
            pass

    async def send(self, method: str, params: dict | None = None, timeout: float = 20.0) -> dict:
        self._id += 1
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[self._id] = fut
        await self._ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(self._id, None)
            raise

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass


CLICK_JS = """
(label) => new Promise((resolve) => {
  const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const wanted = norm(label);
  const deadline = Date.now() + 12000;
  const tryOnce = () => {
    const mainNodes = Array.from(document.querySelectorAll(
      'main button, main [role="tab"], main a, [role="main"] button, [role="main"] [role="tab"]'));
    const anywhere = Array.from(document.querySelectorAll('button, [role="tab"], a'));
    const pick = (nodes) => nodes.find((n) => norm(n.textContent) === wanted)
      || nodes.find((n) => norm(n.textContent).includes(wanted));
    const target = pick(mainNodes) || pick(anywhere);
    if (target) {
      target.click();
      resolve('clicked[' + (mainNodes.includes(target) ? 'main' : 'any') + ']: '
        + norm(target.textContent).slice(0, 80));
      return;
    }
    if (Date.now() > deadline) { resolve('NOT FOUND: ' + wanted); return; }
    setTimeout(tryOnce, 300);
  };
  tryOnce();
})
"""

BELL_JS = """
() => new Promise((resolve) => {
  const deadline = Date.now() + 12000;
  const tryOnce = () => {
    const svg = document.querySelector('.lucide-bell, .lucide-bell-ring');
    const btnFromSvg = svg && svg.closest('button');
    const btnByTitle = Array.from(document.querySelectorAll('button')).find((b) =>
      ((b.getAttribute('title') || '') + ' ' + (b.getAttribute('aria-label') || ''))
        .toLowerCase().includes('notif'));
    const btn = btnFromSvg || btnByTitle;
    if (btn) { btn.click(); resolve('clicked bell'); return; }
    if (Date.now() > deadline) { resolve('notifications button not found'); return; }
    setTimeout(tryOnce, 300);
  };
  tryOnce();
})
"""

SCROLL_JS = """
(where) => {
  window.scrollTo(0, where === 'bottom' ? document.body.scrollHeight : 0);
  return String(window.scrollY);
}
"""


async def eval_expr(cdp: CDP, expr: str) -> str:
    res = await cdp.send(
        "Runtime.evaluate",
        {"expression": expr, "returnByValue": True, "awaitPromise": True, "userGesture": True},
    )
    return str(res.get("result", {}).get("result", {}).get("value"))


async def eval_fn(cdp: CDP, fn_body: str, arg: str) -> str:
    res = await cdp.send(
        "Runtime.evaluate",
        {
            "expression": f"({fn_body})({json.dumps(arg)})",
            "returnByValue": True,
            "awaitPromise": True,
            "userGesture": True,
        },
        timeout=30.0,
    )
    return str(res.get("result", {}).get("result", {}).get("value"))


async def navigate(cdp: CDP, url: str) -> None:
    try:
        await cdp.send("Page.navigate", {"url": url}, timeout=30.0)
    except asyncio.TimeoutError:
        await cdp.send("Page.navigate", {"url": url}, timeout=30.0)


AUTH_LOADING_TEXT = "جاري التحقق من الحساب"


async def wait_content(cdp: CDP, timeout: float = 15.0) -> str:
    probe = ("(document.body && document.body.innerText.includes(" + json.dumps(AUTH_LOADING_TEXT)
             + ")) ? 'loading' : 'ready'")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = await eval_expr(cdp, probe)
        except Exception:
            state = "loading"
        if state == "ready":
            return "ready"
        await asyncio.sleep(0.5)
    return "still-loading"


async def screenshot(cdp: CDP, path: Path) -> int:
    res = await cdp.send(
        "Page.captureScreenshot",
        {"format": "png", "captureBeyondViewport": True},
        timeout=30.0,
    )
    data = base64.b64decode(res["result"]["data"])
    path.write_bytes(data)
    return len(data)


def secret_values() -> list[str]:
    secrets: list[str] = []
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            for key in ("NEXUS_INTERNAL_API_SECRET", "NEXUS_JWT_SECRET", "NEXUS_ADMIN_PIN"):
                if line.startswith(key + "="):
                    value = line.split("=", 1)[1].strip()
                    if value:
                        secrets.append(value)
    if TOKEN_FILE.exists():
        secrets.append(TOKEN_FILE.read_text().strip())
    return secrets


def scan_for_secrets(paths: list[Path]) -> dict:
    needles = secret_values()
    findings: list[dict] = []
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in needles:
            if needle and needle in text:
                findings.append({"file": str(path), "needle_len": len(needle)})
    result = {"scanned_files": [str(p) for p in paths if p.exists()], "leaks": findings, "clean": not findings}
    (EVID / "secret_scan.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


async def run(args: argparse.Namespace) -> int:
    base = args.base.rstrip("/")
    token = TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else ""
    if not token:
        raise SystemExit(f"token missing: {TOKEN_FILE}")
    REDACT.clear()
    REDACT.append(token)

    for d in (SHOTS, EVID):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)

    profile = Path(os.environ["TEMP"]) / f"nexus-walk-profile-{uuid.uuid4().hex[:8]}"
    profile.mkdir(parents=True, exist_ok=True)
    edge = launch_edge(profile)

    ws_url = ""
    try:
        for _ in range(40):
            time.sleep(0.5)
            try:
                pages = [t for t in cdp_list() if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                continue
        if not ws_url:
            raise SystemExit("no CDP page target appeared")

        rec = Recorder()
        cdp = CDP(ws_url, rec)
        await cdp.connect()
        await cdp.send("Page.enable")
        await cdp.send("Runtime.enable")
        await cdp.send("Network.enable")

        rows: list[dict] = []

        # Step 1: unauthenticated login screen (no token yet).
        step = STEPS[0]
        rec.step = step["name"]
        print(f"[1/{len(STEPS)}] {step['name']}", flush=True)
        await navigate(cdp, base + step["url"])
        await asyncio.sleep(step.get("settle", 3.0))
        n = len(list(SHOTS.glob("*.png"))) + 1
        shot_name = f"{n:03d}-{step['name']}-{file_stamp()}.png"
        size = await screenshot(cdp, SHOTS / shot_name)
        rows.append(_row(step, shot_name, size, rec))

        # Inject reader token for every later document.
        await cdp.send(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": f"try {{ localStorage.setItem('nexus-token', {json.dumps(token)}); }} catch (e) {{}}"},
        )
        await eval_expr(cdp, f"localStorage.setItem('nexus-token', {json.dumps(token)}); 'set'")

        for idx, step in enumerate(STEPS[1:], start=2):
            rec.step = step["name"]
            print(f"[{idx}/{len(STEPS)}] {step['name']}", flush=True)
            console_before = len(rec.console)
            http_before = len(rec.http)
            await navigate(cdp, base + step["url"])
            await asyncio.sleep(step.get("settle", 3.0))
            ready_state = await wait_content(cdp)

            outcome = ""
            if step.get("click"):
                if step["click"] == "bell":
                    outcome = await eval_fn(cdp, BELL_JS, "")
                else:
                    outcome = await eval_fn(cdp, CLICK_JS, step["click"])
                await asyncio.sleep(2.0)

            if step.get("expect_text"):
                wanted_text = step["expect_text"]
                found = "MISSING"
                for _ in range(10):
                    body = await eval_expr(cdp, "document.body ? document.body.innerText : ''")
                    if wanted_text in body:
                        found = "OK"
                        break
                    await asyncio.sleep(0.5)
                outcome = f"{outcome} | expect '{wanted_text}': {found}"
            if ready_state != "ready":
                outcome = f"{outcome} | page {ready_state}"

            if step.get("scroll") == "bottom":
                await eval_fn(cdp, SCROLL_JS, "bottom")
                await asyncio.sleep(1.2)
            elif step.get("shot") != "full":
                await eval_expr(cdp, "window.scrollTo(0, Math.min(900, document.body.scrollHeight / 2)); 'mid'")
                await asyncio.sleep(0.8)
                await eval_expr(cdp, "window.scrollTo(0, 0); 'top'")

            n = len(list(SHOTS.glob("*.png"))) + 1
            shot_name = f"{n:03d}-{step['name']}-{file_stamp()}.png"
            try:
                size = await screenshot(cdp, SHOTS / shot_name)
            except Exception as exc:
                shot_name = shot_name.replace(".png", f"-SHOTFAIL-{type(exc).__name__}.png")
                size = 0
            row = _row(step, shot_name, size, rec)
            row["click_outcome"] = outcome
            row["console_errors"] = len(rec.console) - console_before
            row["http_responses"] = len(rec.http) - http_before
            rows.append(row)

        files = {
            "console": (EVID / "console.jsonl").open("w", encoding="utf-8"),
            "http": (EVID / "http_responses.jsonl").open("w", encoding="utf-8"),
            "fail": (EVID / "request_failures.jsonl").open("w", encoding="utf-8"),
            "ws": (EVID / "websocket_events.jsonl").open("w", encoding="utf-8"),
        }
        for row in rec.console:
            files["console"].write(json.dumps(row, ensure_ascii=False) + "\n")
        for row in rec.http:
            files["http"].write(json.dumps(row, ensure_ascii=False) + "\n")
        for row in rec.failures:
            files["fail"].write(json.dumps(row, ensure_ascii=False) + "\n")
        for row in rec.ws:
            files["ws"].write(json.dumps(row, ensure_ascii=False) + "\n")
        for req_id, stats in rec.ws_frames.items():
            files["ws"].write(json.dumps({"frames": {"request_id": req_id[:16], **stats}}, ensure_ascii=False) + "\n")
        for fh in files.values():
            fh.close()

        tsv = OUT / "SCREENSHOTS.tsv"
        with tsv.open("w", encoding="utf-8") as fh:
            fh.write("file\tunits\tstep\turl\taction\tutc\tbytes\tconsole_errors\thttp_responses\tclick_outcome\n")
            for r in rows:
                fh.write(
                    f"{r['file']}\t{r['units']}\t{r['step']}\t{r['url']}\t{r['action']}\t{r['utc']}"
                    f"\t{r['bytes']}\t{r['console_errors']}\t{r['http_responses']}\t{r.get('click_outcome', '')}\n"
                )

        ws_bases = sorted({u for b in rec.per_step.values() for u in b["ws_urls"]})
        summary = {
            "base": base,
            "steps": len(rows),
            "screenshots": len(list(SHOTS.glob("*.png"))),
            "console_errors": len(rec.console),
            "console_warnings": sum(1 for r in rec.console if r["level"] == "warning"),
            "http_responses": len(rec.http),
            "http_4xx": sum(1 for r in rec.http if 400 <= r["status"] < 500),
            "http_5xx": sum(1 for r in rec.http if r["status"] >= 500),
            "request_failures": len(rec.failures),
            "ws_connections": len(rec.ws),
            "ws_url_bases": ws_bases,
            "finished_utc": utc_stamp(),
        }
        (EVID / "walkthrough_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        secret_scan = scan_for_secrets(
            [tsv, EVID / "console.jsonl", EVID / "http_responses.jsonl", EVID / "websocket_events.jsonl"]
        )
        summary["secret_scan_clean"] = secret_scan["clean"]
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        await cdp.close()
        return 0
    finally:
        stop_edge(edge)
        time.sleep(1.0)
        shutil.rmtree(profile, ignore_errors=True)


def _row(step: dict, shot: str, size: int, rec: Recorder) -> dict:
    b = rec.per_step.get(step["name"], {})
    return {
        "file": shot,
        "units": step.get("units", ""),
        "step": step["name"],
        "url": step["url"],
        "action": step.get("click") or step.get("scroll") or "",
        "utc": utc_stamp(),
        "bytes": size,
        "console_errors": b.get("console_errors", 0),
        "http_responses": "",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:3100")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
