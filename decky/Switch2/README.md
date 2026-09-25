# Switch 2 (NUXBT) Decky plugin

QAM controls for the Switch 2 remote-play Pro Controller bridge
(`scripts/nuxbt-sunshine-bridge.py` via `scripts/nuxbt-api.py`).

## Actions

| Button | Behavior |
|--------|----------|
| **Reconnect (MAC)** | Hard restart: **prepare USB radio** (power-cycle `hci1`) then MAC reconnect |
| **Grip / Order** | Hard restart: **prepare USB radio** then advertise + hold L+R |
| **Start bridge** | Same prep, then reconnect mode |
| **Stop bridge** | Stop the bridge process |
| **Refresh** | Re-poll status |

Every hard **Grip / Reconnect / Start** runs `scripts/nuxbt-prepare-radio.py` first:

1. Ensure BlueZ `--compat --noplugin=*` (NOPASSWD helper if missing)
2. Power off onboard MT7922 (`hci0`)
3. **Power-cycle** TP-Link dongle (`hci1`): `Powered=false` → ~1s → `Powered=true`
4. Set HCI name `Pro Controller` + class `0x002508` (gamepad)

That off→on on `hci1` is what unstuck Grip advertise when the Switch saw nothing (no ACL). Soft flag-only (`--soft`) skips prep — QAM uses hard.

After Grip **L+R**, leaving Change Grip/Order tears the pairing ACL; the bridge **MAC-reconnects in-process** (stable-link + backoff — no connect/crash thrash). Day-to-day: **Reconnect**. Grip only for first pair / MAC change / paused flap. **HOME** on the Switch is Plus+L+D-Pad Down (Guide alone still works).

Status shows bridge up/down, BlueZ Switch link on `hci1`, and the Sunshine source pad (Odin/Thor/phone).

## Install / reload

```bash
./scripts/ensure-switch2-decky.sh
```

Reload name is **Switch 2**. Close and reopen QAM after reload.

PluginLoader is root — `main.py` runs `nuxbt-api.py` as user `deck`.
Do not `sudo systemctl --user`. Additive Switch RP only.
