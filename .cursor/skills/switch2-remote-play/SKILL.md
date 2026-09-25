---
name: switch2-remote-play
description: >-
  Handover and investigation plan for physical Nintendo Switch 2 remote play
  through this SteamOS host (Moonlight → Sunshine → NXBT → Switch 2, plus HDMI
  capture). Use when the user mentions Switch 2 remote play, NXBT, Switch
  capture card streaming, or console GameStream bridging.
---

# Switch 2 remote play (handover)

**Steam Machine** (`steammachine` / `gpc`).

**Hard rule:** this project must **not mess with anything already built**. Additive only — new scripts/services/apps for Switch 2 remote play. Do not change working dual-stream, EmuPads mux defaults, Pad Hide, Tender wraps, Eden/Cemu/Azahar binds, sunshine-ds/kms, Tailscale, or Syncthing to “make Switch easier.”

## North star (immediate)

> Make this PC appear to the physical Switch 2 as a Bluetooth Pro Controller (NXBT or best Linux-native equivalent). Prove buttons/sticks in a real game before any video/automation work.

```text
Moonlight → Sunshine virtual pad → (later) evdev bridge → NXBT → BT → Switch 2
```

Video/OBS/capture/KVM are **later**. Wake/dock/always-on is **deferred**. **One console only** (Switch 2) until that path works.

## Status (2026-09-25)

**Working end-to-end (gates A–G largely green):** remote Odin/Thor Moonlight pad → Sunshine → NUXBT → Switch 2; HDMI capture tile fullscreen under Game Mode; Moonlight sees the session; capture audio reaches the stream via HDMI leaf loopback. **Reliability landed:** pinned controller MAC, USB dongle radio prep on QAM Grip/Reconnect, MAC rejoin after leaving Grip/Order (stable-link + backoff, no connect/crash thrash), HOME = Plus+L+Down.

**Capture Steam tile:** `ensure-switch2-capture-shortcut.sh` → non-Steam **Nintendo Switch 2** (`switch2-capture-viewer.sh`). **mpv** AppImage (`ensure-switch2-mpv.sh` → `~/.local/bin/mpv-switch2`, `vo=x11` under gamescope; ffplay fallback). **Default 1280×720@60** — MS2109 USB2 only delivers ~30fps at 1080p MJPEG; 720p is real 60. Override `SWITCH2_CAPTURE_WIDTH/HEIGHT`. **Audio:** Pulse `module-loopback` from MS2109 → HDMI leaf sink (same path Sunshine `audio_sink` captures) — not `sink-sunshine-stereo`. `SWITCH2_CAPTURE_AUDIO=0` disables. If STREAMON busy: Switch HDMI into card or `sudo usbreset 534d:2109` / viewer PCI-rebind (`hide-controllers-sysfs.sh usb-pci-rebind`).

**Latency (pad → V4L2, Test Input Devices, 2026-09-24):** `scripts/measure-switch2-capture-latency.py` — median ~**141 ms** (n=6; mean ~340 ms with outliers; min ~29 ms max ~833 ms). Includes BT/NUXBT + Switch UI + HDMI + MS2109 MJPEG dequeue. **Not** included: mpv/ffplay, gamescope, Sunshine encode, Wi‑Fi, Moonlight decode (~+30–80 ms rough). Native Switch press→pixels is already a large share; software will not halve this number alone.

**USB dongle on De-FanGoH:** RTL8761BU `hci1` `50:3D:D1:EE:D3:2B`; MT7922 `hci0` stays **DOWN**. BlueZ override (`--compat --noplugin=*`) via `sudo -n …/hide-controllers-sysfs.sh nuxbt-bluez enable` (NOPASSWD). **QAM Grip / Reconnect / Start** (and CLI `nuxbt-api`) run `scripts/nuxbt-prepare-radio.py` first: ensure override, power off `hci0`, **power-cycle `hci1`** (`Powered=false` → sleep → `true`), set HCI name `Pro Controller` + class `0x002508`. That off→on clears a wedged advertise with no ACL. **Controller MAC is pinned** in `~/.config/nuxbt/controller-mac`. Do **not** randomize. Reconnect: **`scripts/nuxbt-api.py reconnect|grip`**. After a BlueZ wedge, prefer QAM Grip (prep + advertise) while Switch is on Change Grip/Order. Kill leftover bridge PIDs by argv (`…/nuxbt-sunshine-bridge.py` as its own arg) — never `pgrep -f` / never match agent shells that embed the script path in `bash -c`.

**Input bridge:** `scripts/nuxbt-bridge.sh` → `scripts/nuxbt-sunshine-bridge.py`. **Mux-like:** NUXBT↔Switch is the long-lived sink; Sunshine/Odin pads hotplug as sources (Moonlight drop → idle to Switch; reconnect picks up the new event node without re-pairing). Face buttons by position (**west→X north→Y**), Plus/Minus inverted vs naive SDL, **HOME = Plus + L + D-Pad Down** (Guide still works; L/Plus/Down suppressed during the combo), 120 Hz. **Steam overlay / QAM / Home (769)** → idle to Switch (drain pad, discard presses; also honors `$XDG_RUNTIME_DIR/emupads-mute` via `start-emu-steam-ui-inhibit.sh`). EmuPads off for the session. NUXBT is **Bluetooth HID only**.

**Stay connected / advertise:**
- **A)** On Switch drop the bridge **auto-respawns** (MAC reconnect first; if stuck ~25s → advertise).
- **B)** After Grip **L+R hold completes**, arm **MAC reconnect mode** — leaving Change Grip/Order (press +) tears the pairing ACL (often NUXBT `crashed`); we **rejoin in-process by Switch MAC** with backoff. Crash counter only clears after a **20s stable** link (`NUXBT_STABLE_LINK_S`); after `NUXBT_CRASH_RECONNECT_MAX` (default 6) unstable crashes, **pause** until QAM Grip/Reconnect (do not thrash). Explicit Grip still advertises.
- **C)** While running: `touch $XDG_RUNTIME_DIR/nuxbt-want-grip` → advertise + hold L+R; `touch …/nuxbt-want-reconnect` → MAC reconnect. Or `nuxbt-api.py grip|reconnect` (hard; includes radio prep).
- **Decky QAM:** `decky/Switch2/` → `scripts/ensure-switch2-decky.sh` (reload name **Switch 2**). **Grip / Reconnect / Start** all call `nuxbt-prepare-radio.py` then hard-restart under `systemd-run --user`. Soft flag-only is weaker — prefer hard.

- Skill decisions locked (Decky first, then Game Mode DS; one console; no-touch existing stack).
- **NUXBT** works on **lab** (BCM43438 + USB) and **De-FanGoH** (USB only; MT7922 fails).
- Lab/USB stick: TP-Link `2357:0604` → **RTL8761BU**. Stock `nuxbt demo` creates a controller on **every** adapter — force a single adapter path.
- Without BlueZ `--noplugin=*`, Switch flaps `RequestAuthorization` / connect-reset; do not skip the override.

### Why lab works and De-FanGoH onboard does not

| | **lab (works)** | **De-FanGoH MT7922 (no pair)** |
|--|-----------------|-------------------------|
| Radio | BCM43438 UART **and** USB RTL8761BU (`2357:0604`) | MediaTek **MT7922** combo (`0e8d:0616`) |
| Proof | USB-forced demo 2026-09-24: `Finished!` ACL up | Software OK; radio stalls |
| Runtime | Native `~/code/nuxbt/.venv` | Host `~/code/nuxbt-host` + capped `bin/python3-nuxbt` |

**De-FanGoH path (proven):** USB RTL8761BU only; keep MT7922 powered off; create controller only on `/org/bluez/hci1`; QAM Grip/Reconnect with radio prep.

**Dongle note:** Lab stick is Realtek RTL8761BU (UB500-class VID), not CSR `0a12:0001`. It worked on lab against Switch 2. Prefer CSR UB400/UB4A if buying another.

## Decisions (locked)

| Topic | Decision |
|-------|----------|
| Existing stack | **Do not break or rework** dual-stream, EmuPads, Pad Hide, Tender, emulator binds, Decky Sunshine, sunshine-ds, Tailscale, Syncthing, or skipped Switch 2 pad→PC bridge. Isolate Switch RP in its own start/stop path. |
| Existing `switch2-controllers-linux` / `ensure-switch2-controllers` | Stays **skipped forever** (`PLAYBOOK_SKIP` default). Opposite direction (pad → PC). Do not enable for this project. |
| Consoles in scope | **Switch 2 only** until remote play works end-to-end. No Switch 1, no KVM, no dual-console switching. |
| First milestone | Controller only (NXBT path). Not video. |
| BT adapter | Prefer **motherboard** Bluetooth. Dedicated USB dongle only if onboard fails for chipset/MAC/agent reasons, not as day-one spend. |
| While Switch RP session is up | **EmuPads off** (session-scoped only; restore previous mux state on exit). Sunshine Moonlight pad **shared with Steam** (no EVIOCGRAB / exclusive grab that blocks overlay nav). |
| Sunshine servers | Prefer **Decky Sunshine `:47989` first**, then **sunshine-ds-kms Game Mode `:48200`**. Desktop DS `:48100` is optional later. **MVP**: Decky only — do not dual-stream Switch capture. Do not alter existing Cemu/Azahar DS apps. |
| Video viewer | Prefer **non-OBS** first (see below). Capture card exists; OBS is fallback if mpv/ffplay fail under gamescope. |
| Latency polish | **Make it work first**, then measure and optimize. |
| Switch wake / dock power | **Deferred**. Manual wake OK for MVP. |
| Switch 1 + HDMI/USB KVM | **Out of scope** until Switch 2 RP works. Do not purchase. |
| reWASD / ESP32 | Fallback only if NXBT-class BT Pro Con emulation fails Switch 2. Prefer not buying ESP32 until a meaningful fallback path is chosen. |

## Explicit non-goals (until Switch 2 controller MVP passes)

- Touching or “improving” existing GameStream / emulator / Decky paths as a side effect
- OBS / capture card Steam tile polish
- Fullscreen Gaming Mode automation beyond a manual test
- Switch wake / dock scripts
- Switch 1, KVM, or dual-console switching
- Enabling `ensure-switch2-controllers` / pairing Switch 2 pads to this PC
- Changing sunshine-ds dual-stream / GamePad inject / EmuPads **defaults** or emulator bind scripts
- Buying a second Bluetooth adapter “just in case”
- Global BlueZ / Steam Bluetooth changes that break normal Game Mode play when Switch RP is not running

## Architecture (target)

```text
Remote (Thor / Odin / Deck / phone)
        │ Moonlight
        ▼
SteamOS host
  ├── Sunshine → virtual gamepad → bridge → NXBT → BT HID → Switch 2
  └── Capture card (HDMI) → low-latency viewer → Sunshine encode → Moonlight
```

Controller and video are independent pipes. Controller milestone does **not** require the capture card to be plugged in.

---

## Investigation order (stop on failure)

1. **Package NXBT (or chosen fork) on SteamOS** — seamless bring-up after reboot/updates (venv/Distrobox; prefer playbook-style `ensure-*.sh` later).
2. **Pair emulated Pro Controller with Switch 2** (Controllers → Change Grip/Order).
3. **Verify sticks/buttons in a real game** (not only Grip/Order).
4. **Reconnect gate** (document result; ideal = reconnect without Grip/Order; acceptable MVP = open Grip/Order once per session — record which).
5. **Map how Sunshine exposes the Moonlight pad** on this box (`045e:02ea` ghost, `/dev/input/event*`, interaction with Steam virtual).
6. **Prototype** `Sunshine pad → evdev → NXBT` with EmuPads **off**, pad **shared** with Steam.
7. **Stability** (30+ min session) — latency numbers come after “works.”
8. **HDMI capture** → low-latency fullscreen viewer (mpv/ffplay first) → Sunshine app / Steam tile.
9. **Automate** start/stop with the “Nintendo Switch 2” entry.
10. **Only after Switch 2 RP works:** optional Switch 1 + KVM as a separate project.

If step 2 fails because Switch 2 **rejects** the emulated Pro Con protocol (after MAC/agent/fork triage), investigate Linux alternatives, then reWASD/ESP32 — do not buy ESP32 solely to “try Proton.”

---

## Controller stack

### Primary: NUXBT (NXBT fork)

- Use **[hannahbee91/nuxbt](https://github.com/hannahbee91/nuxbt)** on this box (upstream NXBT is stale / Python-painful).
- Install / restore: `scripts/ensure-nuxbt.sh` → host `~/code/nuxbt-host/.venv` (not Distrobox).
- Expect possible needs: Pro Controller alias, **stable** MAC (pinned dongle Address or fixed Nintendo OUI `7C:BB:8A:DE:F0:01` — never random per spawn), BlueZ agent trust, Grip/Order for **first** pair or after MAC/BlueZ wipe.
- `scripts/nuxbt-bluez-override.sh enable|disable|status` — **host** tmpfs BlueZ override (`--compat --noplugin=*`) + setcap on `~/code/nuxbt-host/bin/python3-nuxbt`. Never setcap `/usr/bin/python*`. Never `nuxbt toggle` inside Distrobox.

### Alternatives if NXBT is painful (same direction: PC → Switch)

| Project | Notes |
|---------|--------|
| [joycontrol](https://github.com/mart1nro/joycontrol) | Classic BT Pro Con / Joy-Con emulation; also BlueZ-heavy; similar pairing model. |
| libnxctrl | Mostly NXBT-backed — not a different radio stack. |
| USB gadget / ESP32 HID | Hardware fallback; only after software BT fails. |
| reWASD + ESP32 | Windows-centric; Proton is unlikely to replace kernel drivers. GUI-over-Proton ≠ validated HID path. |

**Not alternatives for this project:**

- `switch2-controllers-linux` — wrong direction (Switch 2 pad → PC). Stays skipped.
- DSTX / similar — pad → Xbox uinput on Linux, not Switch host emulation.

### Packaging preference

Whatever is **most seamless** after reboot and SteamOS updates:

- Prefer home-dir venv (pattern like other playbook tools) or Distrobox with BT access.
- Aim for a future `ensure-switch2-remote-play.sh` (not written until MVP works).
- Manual pairing steps may stay `record_manual` forever.

### BlueZ coexistence

- Do **not** turn on the skipped Switch 2 pad bridge.
- Any BlueZ / Steam BT tweak for NXBT must be **session-scoped or fully reversible** so normal Game Mode (no Switch RP) keeps working as today.
- Motherboard BT first; USB dongle only if onboard cannot advertise/pair stably.

### Bridge rules (Phase 3)

- Input identity: pin Sunshine Moonlight pad (name / VID:PID / path). Ignore EmuPads, leftover ghosts, physical Xbox when possible.
- EmuPads: **off** for the Switch RP session.
- Do **not** exclusive-grab the Sunshine pad — Steam needs it for overlay / QAM nav.
- Map 1:1 sticks, d-pad, ABXY, L/R/ZL/ZR, +/−, Home, stick clicks. No fancy remaps unless required.
- **Implemented:** `scripts/nuxbt-bridge.sh` / `scripts/nuxbt-sunshine-bridge.py` (prefer `Sunshine (libvirtualhid)*`, skip `28de:11ff` / EmuPads; face buttons by position; 120 Hz `set_controller_input`).

---

## Video stack (after controller MVP)

Sunshine does **not** ingest V4L2 directly. It captures the display / launched app window. So:

```text
Switch 2 HDMI → capture card → /dev/videoN → fullscreen viewer → Sunshine → Moonlight
```

### Prefer over OBS

| Option | Role |
|--------|------|
| **mpv** | Default viewer (`switch2-capture-viewer.sh`): host AppImage via `ensure-switch2-mpv.sh`, `--profile=low-latency --untimed --vo=x11` (Flatpak cannot open MS2109 V4L2 ACLs). |
| **ffplay** | Fallback if mpv VOs fail: `-fflags nobuffer -flags low_delay -framedrop`. |
| **Audio** | Pulse `module-loopback` MS2109 → HDMI leaf (Sunshine captures HDMI.monitor). Do not use `sink-sunshine-stereo`. |
| **Consolation** | Dedicated UVC viewer; optional if mpv fails UX-wise. |
| **OBS** | Fallback if gamescope/Flatpak/audio needs a compositor path — not the default. |

HDCP: if the capture is black, check Switch HDMI/HDCP settings before blaming Sunshine.

Steam tile long-term: **Nintendo Switch 2** launches viewer (+ later bridge/NXBT), not the OBS UI.

### Capture card (this box) + upgrade notes (2026-09-24)

**Now:** MacroSilicon **MS2109** (`534d:2109`) → `/dev/video0` on USB **2.0**. Advertises 1080p60 MJPEG but **measured ~30fps** at 1920×1080; **720p60 is real ~60fps** (viewer default). Chop at 1080p is the card bandwidth, not Moonlight. Encoder path separately fixed: `encoder = vaapi` + `minimum_fps_target = 60` (Mesa on RX 9060 XT). Host `sunshine-ds-kms` reads shaders from `/home/deck/sdsast` → `~/.local/share/sunshine-ds/assets`.

Switch 2 dock: **4K60** or **1080p/1440p @ 120** — **4K120 is irrelevant**; **1080p120** is the useful high-FPS target. Prefer USB3 **NV12/raw UVC**, not USB2 MJPEG.

| Goal | Buy |
|------|-----|
| Best SteamOS / Linux UVC balance (optional community 1080p120) | **Elgato HD60 X** |
| Cheapest true 1080p120 UVC | **ezcap321** (HDMI 1.4 / grey-market risk) |
| Linux “just works,” 60 fps OK | **Magewell USB Capture HDMI 4K Plus** (not a 120 pick) |
| Avoid for SteamOS automation | **AVerMedia GC553** (no Linux); **Elgato 4K60 Pro PCIe** unless you’ll maintain `sc0710` DKMS |

Research brief: [Research 120fps capture cards](bc-cf51c2fe-929f-5790-b733-1e4b4153a2f0).

### Sunshine ports

- **Prefer:** Decky Sunshine `:47989`, then Game Mode sunshine-ds-kms `:48200`.
- Desktop DS `:48100` only if useful later.
- Dual-panel / gamescope-virtual is **out of scope** for Switch capture.
- Do not alter existing Cemu/Azahar DS app entries.

---

## Success gates

| Gate | Pass |
|------|------|
| A | Emulated Pro Con appears on Switch 2 Grip/Order |
| B | Buttons/sticks work in a real game |
| C | Reconnect behavior documented (with or without Grip/Order) |
| D | Sunshine Moonlight pad identified under Linux with EmuPads off |
| E | Live bridge: remote pad → Switch 2 |
| F | Capture card fullscreen via mpv/ffplay (no OBS required) |
| G | Moonlight sees that fullscreen session |
| H | Start/stop automation for the Steam/Moonlight entry |

**Ship controller MVP at E.** Video starts at F. As of 2026-09-24 on De-FanGoH: A–G proven in session; H is the Steam tile + Decky Switch 2 QAM (polish remaining below).

---

## Potential improvements (do not block daily use)

Ordered by expected impact. Keep additive — do not rewrite dual-stream / EmuPads / Tailscale to chase these.

### Latency / video quality

| Idea | Notes |
|------|--------|
| **Better capture card** | MS2109 USB2 MJPEG is the main host-side video tax. **Elgato HD60 X** (~45–65 ms capture, Linux UVC) or **Magewell USB Capture HDMI Gen 2 / 4K Plus**; cheap **MS2130 / UGREEN “4K30”** USB3 helps 1080p60 more than lag. UGREEN alone will not halve the ~141 ms pad→V4L2 median. |
| **Dock at 1080p60** | Avoid 4K-in → card downscale; small win, free to try. |
| **Host `mpv` (pacman)** | AppImage is stuck on `vo=x11` (no GLX/GBM/`libsensors` under gamescope). System mpv may use `vo=gpu` and shave a little viewer delay. Needs `steamos-readonly` + sudo — `record_manual` if desired. |
| **Sunshine / Moonlight knobs** | Tight bitrate, Performance / lowest delay on Thor, client VSync off. Encode/net is outside the V4L2 probe. |
| **mpv audio in-process** | Today audio is Pulse loopback (reliable for Sunshine HDMI capture). Optional: mpv `--audio-file=av://pulse:…` to one process — only if loopback drifts. |

### Reliability / UX

| Idea | Notes |
|------|--------|
| **Bridge process hygiene** | `systemd-run` `KillMode=process` can leave orphan `nuxbt-sunshine-bridge.py` children after stop/restart. Harden `_stop_bridge` / unit `KillMode=control-group` (test Decky QAM still cannot SIGTERM the live bridge). |
| **BlueZ wedge recovery** | `org.freedesktop.DBus.Error.NoReply` → `nuxbt-bluez enable` (restarts bluetoothd with override) then **Reconnect** (pinned MAC). **Grip** only if that fails on Change Grip/Order. Could auto-detect NoReply in `nuxbt-api.py` and re-enable once. |
| **WirePlumber V4L2 hold** | Camera monitor leaves `STREAMON` EBUSY with no userspace opener. Viewer already `pw-cli destroy`s nodes; optional WirePlumber rule to not auto-open MS2109. |
| **Grip still sometimes required** | Needed for **first pair**, after changing `~/.config/nuxbt/controller-mac`, or after a BlueZ wipe / paused flap. After Grip L+R, leaving the menu should MAC-reconnect (with backoff). Day-to-day: QAM **Reconnect**. |
| **Stable controller MAC** | `scripts/nuxbt-pin-controller-mac.py` + `~/.config/nuxbt/controller-mac`. Never randomize per spawn. Body/button colours fixed (`NUXBT_COLOUR_*`). |
| **Post-Grip crash → rejoin** | **Done (2026-09-25):** in-process MAC reconnect; clear counter only after `NUXBT_STABLE_LINK_S` (20s); exponential backoff; pause after max unstable crashes (no connect/disconnect thrash). |
| **USB dongle radio prep** | **Done:** `scripts/nuxbt-prepare-radio.py` — QAM Grip/Reconnect/Start and `nuxbt-bridge.sh` power-cycle `hci1`, keep `hci0` off, set Pro Controller name/class. |
| **HOME chord** | **Done:** Plus + L + D-Pad Down (Guide alone still works); L/Plus/Down suppressed during the combo. |
| **Decky UX** | Status copy when advertising vs connected; soft reconnect avoided as default. Optional: one-tap clean restart waiting for single bridge PID. |
| **Steam tile one-shot** | Launch viewer + ensure BlueZ override + start bridge (or attach if already up) from one desktop entry — without touching other Game Mode services. |

### Out of scope / defer

- Switch wake / dock always-on
- Switch 1 + KVM
- Dual-panel GameStream for Switch capture
- Sub-100 ms pad→Thor remote (not realistic through BT + Switch UI + USB2 capture + encode + Wi‑Fi)
- Enabling skipped `ensure-switch2-controllers` (wrong direction)

---

## Fallback: reWASD / ESP32

Only if software BT Pro Con emulation cannot satisfy gates A–B after fork/MAC/agent triage on motherboard BT.

- Proton may run a GUI; that does **not** prove Windows virtual-controller drivers or ESP32 HID.
- Do not purchase ESP32/reWASD hardware until the NXBT-class path is declared failed **or** a cheap ESP32 is explicitly approved as the fallback instrument.
- Prefer researching other Linux/USB gadget options before committing to Windows-in-Proton.

---

## Future: Switch 1 + Switch 2

**After** Switch 2 remote play works (gates through H). Not before.

- One console first is mandatory; dual-console is a separate project.
- Prefer software pad selection if still on NXBT; KVM purchase only if still needed then.
