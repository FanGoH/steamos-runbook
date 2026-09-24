#!/usr/bin/env python3
"""Phone WebGUI for fgpc. Serves fgpc/web and POST /api/run.

  python3 scripts/fgpc-web.py
  python3 scripts/fgpc-web.py --self-test
  python3 scripts/fgpc-web.py --print-bind

Same refuse list as scripts/fgpc-api.py. Never --force hide.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _add_src() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / "fgpc" / "src",
        Path("/home/deck/steamos-playbook/fgpc/src"),
    ]
    for src in candidates:
        if (src / "fgpc" / "web.py").is_file():
            sys.path.insert(0, str(src))
            return src
    sys.path.insert(0, str(candidates[0]))
    return candidates[0]


_add_src()

from fgpc.web import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
