# Loaded via PYTHONPATH when launching the NUXBT bridge (see nuxbt-bridge.sh).
# Patches ControllerProtocol.process_commands in the controller *child* process
# so Switch HD rumble bytes are mirrored to $XDG_RUNTIME_DIR/nuxbt-switch-rumble.
from __future__ import annotations


def _install_rumble_hook() -> None:
    try:
        from nuxbt.controller.protocol import ControllerProtocol
    except Exception:
        return
    if getattr(ControllerProtocol.process_commands, "_nuxbt_rumble_hook", False):
        return

    import os
    from pathlib import Path

    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    rumble_path = runtime / "nuxbt-switch-rumble"
    orig = ControllerProtocol.process_commands

    def process_commands(self, data):  # type: ignore[no-untyped-def]
        if data and len(data) >= 10 and data[0] == 0xA2:
            try:
                rumble_path.write_bytes(bytes(data[2:10]))
            except OSError:
                pass
        return orig(self, data)

    process_commands._nuxbt_rumble_hook = True  # type: ignore[attr-defined]
    ControllerProtocol.process_commands = process_commands  # type: ignore[method-assign]


try:
    _install_rumble_hook()
except Exception:
    pass
