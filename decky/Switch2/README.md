# Switch 2 (NUXBT) Decky plugin

QAM controls for the Switch 2 remote-play Pro Controller bridge
(`scripts/nuxbt-sunshine-bridge.py` via `scripts/nuxbt-api.py`).

## Actions

| Button | Behavior |
|--------|----------|
| **Reconnect (MAC)** | Touch `nuxbt-want-reconnect`, or start the bridge if down |
| **Grip / Order** | Advertise + hold L+R (or `nuxbt-want-grip` if already up) |
| **Start bridge** | Start reconnect mode |
| **Stop bridge** | Stop the bridge process |
| **Refresh** | Re-poll status |

Status shows bridge up/down, BlueZ Switch link on `hci1`, and the Sunshine
source pad (Odin/Thor).

## Install / reload

```bash
./scripts/ensure-switch2-decky.sh
```

Reload name is **Switch 2**. Close and reopen QAM after reload.

PluginLoader is root — `main.py` runs `nuxbt-api.py` as user `deck`.
Do not `sudo systemctl --user`. Additive Switch RP only.
