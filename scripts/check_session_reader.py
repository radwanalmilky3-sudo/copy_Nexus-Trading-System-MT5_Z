"""Read-only session-export verifier. Does not initialise a terminal or database."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime,timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from services.nexus_data.quality.session_contracts import load_calendar_policy,parse_session_export
from services.nexus_data.quality.session_store import evaluate_export,read_export


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export',type=Path,required=True)
    parser.add_argument('--policy',type=Path,required=True)
    args=parser.parse_args()
    try:
        now=datetime.now(timezone.utc)
        raw=read_export(args.export)
        export=parse_session_export(raw,now=now)
        policy=load_calendar_policy(args.policy)
        status=evaluate_export(export,policy,now,hashlib.sha256(raw).hexdigest())
        print(status.model_dump_json())
        return 0 if status.state=='ready' else 2
    except (OSError,ValueError,UnicodeError):
        print(json.dumps(dict(state='invalid',reason='Export or local policy validation failed')))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
