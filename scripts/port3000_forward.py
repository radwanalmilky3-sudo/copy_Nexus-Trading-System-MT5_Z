#!/usr/bin/env python3
"""Raw TCP forwarder :3000 -> :3100 (N3/T-011 — «إضافة» منشأ :3000).

يجعل http://localhost:3000 منشأ تصفح حقيقياً بتمرير خام إلى الداشبورد
على :3100. لا يفهم HTTP — ينسخ البايتات فقط، لذا لا يضيف رؤوساً ولا
يقيّم CORS (نفس عقد rewrites في next.config.js للمنشأ نفس-الأصل).

التشغيل:  python3 scripts/port3000_forward.py   (daemon عبر nexus_heal.sh)
السجل:    logs/port3000_forward.log
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

LISTEN_PORT = 3000
TARGET_PORT = 3100
TARGET_HOST = "127.0.0.1"


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _handle(
    creader: asyncio.StreamReader, cwriter: asyncio.StreamWriter
) -> None:
    try:
        treader, twriter = await asyncio.open_connection(TARGET_HOST, TARGET_PORT)
    except Exception:
        try:
            cwriter.close()
            await cwriter.wait_closed()
        except Exception:
            pass
        return
    await asyncio.gather(_pipe(creader, twriter), _pipe(treader, cwriter))


async def main() -> None:
    server = await asyncio.start_server(_handle, "0.0.0.0", LISTEN_PORT)
    log_dir = Path(__file__).resolve().parents[1] / "logs"
    log_dir.mkdir(exist_ok=True)
    (log_dir / "port3000_forward.log").write_text(
        f"forwarding :{LISTEN_PORT} -> :{TARGET_PORT} (pid {os.getpid()})\n"
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
