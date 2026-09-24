#!/usr/bin/env python3
"""JSON API for Decky FGPC (and SSH). Does not need the Typer venv.

  python3 scripts/fgpc-api.py dump
  python3 scripts/fgpc-api.py dump --no-live
  python3 scripts/fgpc-api.py run stream start-kms
  python3 scripts/fgpc-api.py run hide off --id usb:045e:028e:5F19FC0A
  python3 scripts/fgpc-api.py self-test

Never passes --force on hide. Refuse host/mode/complete (SSH ``fgpc`` only).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _add_src() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / "fgpc" / "src",
        Path("/home/deck/steamos-playbook/fgpc/src"),
    ]
    for src in candidates:
        if (src / "fgpc" / "api.py").is_file():
            sys.path.insert(0, str(src))
            return src
    sys.path.insert(0, str(candidates[0]))
    return candidates[0]


_add_src()

from fgpc.api import dump, run_action, self_test  # noqa: E402


def _print(data: object) -> int:
    print(json.dumps(data, indent=None))
    if isinstance(data, dict) and data.get("ok") is False:
        return int(data.get("rc") or 2)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="fgpc JSON API for Decky / SSH")
    sub = parser.add_subparsers(dest="cmd", required=True)

    dump_p = sub.add_parser("dump", help="Catalog + live stream/screen/pad/hide")
    dump_p.add_argument(
        "--no-live",
        action="store_true",
        help="Catalog only (self-test / no scripts)",
    )

    run_p = sub.add_parser("run", help="One catalog action")
    run_p.add_argument("group", help="stream | screen | pad | hide | saves | emu")
    run_p.add_argument("action", help="start-kms | paint | dual | mode | off | …")
    run_p.add_argument("--id", dest="pad_id", default="", help="pad or window id")
    run_p.add_argument("--mode", default="", help="shared|multi or auto|on|off")
    run_p.add_argument("--emu", default="all")
    run_p.add_argument("--display", default="")
    run_p.add_argument("--target", default="", help="cemu | azahar")
    run_p.add_argument("--hidden", default="")

    sub.add_parser("self-test", help="Offline catalog + refuse checks")

    args = parser.parse_args()
    if args.cmd == "dump":
        return _print(dump(live=not args.no_live))
    if args.cmd == "self-test":
        data = self_test()
        return _print(data) if data.get("ok") else (_print(data) or 1)
    if args.cmd == "run":
        hidden: object | None = args.hidden or None
        return _print(
            run_action(
                args.group,
                args.action,
                pad_id=args.pad_id,
                mode=args.mode,
                emu=args.emu,
                display=args.display,
                window_id=args.pad_id if args.group == "screen" else "",
                target=args.target,
                hidden=hidden,
            )
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
