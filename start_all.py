"""Compatibility launcher kept for old docs/scripts.

The real supervisor is ``run.py``: it spawns every service with the correct
uvicorn command (``python -m uvicorn services.<name>.main:app --app-dir <root>``),
waits for nexus-data's DuckDB writer before starting peers, health-gates each
port and auto-restarts crashes.

This module no longer spawns processes itself -- the previous implementation ran
``python -m services.<name>.main`` which has no ``__main__`` block, so every
service exited silently and every port check failed.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    print("=== Starting Nexus System (via run.py supervisor) ===")
    # run.py starts Redis-checked services + dashboard and keeps them alive.
    return subprocess.call([sys.executable, str(ROOT / "run.py"), *sys.argv[1:]], cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
