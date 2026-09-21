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

## Decisions (locked)

| Topic | Decision |
|-------|----------|
| Existing stack | **Do not break or rework** dual-stream, EmuPads, Pad Hide, Tender, emulator binds, Decky Sunshine, sunshine-ds, Tailscale, Syncthing, or skipped Switch 2 pad→PC bridge. Isolate Switch RP in its own start/stop path. |
| Existing `switch2-controllers-linux` / `ensure-switch2-controllers` | Stays **skipped forever** (`PLAYBOOK_SKIP` default). Opposite direction (pad → PC). Do not enable for this project. |
| Consoles in scope | **Switch 2 only** until remote play works end-to-end. No Switch 1, no KVM, no dual-console switching. |
| First milestone | Controller only (NXBT path). Not video. |
| BT adapter | Prefer **motherboard** Bluetooth. Dedicated USB dongle only if onboard fails for chipset/MAC/agent reasons, not as day-one spend. |
| While Switch RP session is up | **EmuPads off** (session-scoped only; restore previous mux state on exit). Sunshine Moonlight pad **shared with Steam** (no EVIOCGRAB / exclusive grab that blocks overlay nav). |
| Sunshine servers | End state should work through **all three** (`:47989` Decky, `:48100` desktop DS, `:48200` Game Mode kms) because Sunshine mainly encodes whatever is on screen / launched as an app. **MVP**: prove one path first (prefer Decky `:47989` Desktop app) — do not dual-stream this. Do not alter existing Cemu/Azahar DS apps. |
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
10. Only then: Switch 1 + KVM design.

If step 2 fails because Switch 2 **rejects** the emulated Pro Con protocol (after MAC/agent/fork triage), investigate Linux alternatives, then reWASD/ESP32 — do not buy ESP32 solely to “try Proton.”

---

## Controller stack

### Primary: NXBT family

- Upstream: [Brikwerk/nxbt](https://github.com/Brikwerk/nxbt) (aging; Python/BlueZ friction).
- Community: forks / fixed builds (e.g. NUXBT, typenoob-style packages) — pick whatever **installs cleanly on this host** and pairs to Switch 2.
- Expect possible needs: Pro Controller alias, MAC prefix spoof (`7C:BB:8A…`), BlueZ agent trust, Grip/Order for first pair / reconnect.

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

---

## Video stack (after controller MVP)

Sunshine does **not** ingest V4L2 directly. It captures the display / launched app window. So:

```text
Switch 2 HDMI → capture card → /dev/videoN → fullscreen viewer → Sunshine → Moonlight
```

### Prefer over OBS

| Option | Role |
|--------|------|
| **mpv** | Best first try: `mpv av://v4l2:/dev/videoN --profile=low-latency --untimed --no-cache --fullscreen` (tune format via `v4l2-ctl`). |
| **ffplay** | Minimal: `-fflags nobuffer -flags low_delay -framedrop`. |
| **Consolation** | Dedicated UVC viewer; optional if mpv fails UX-wise. |
| **OBS** | Fallback if gamescope/Flatpak/audio needs a compositor path — not the default. |

Audio: capture-card ALSA/Pulse for the Switch session only — do **not** rewrite the proven Cemu dual-stream HDMI / VSS capture recipes. Defer polish.

HDCP: if the capture is black, check Switch HDMI/HDCP settings before blaming Sunshine.

Steam tile long-term: **Nintendo Switch 2** launches viewer (+ later bridge/NXBT), not the OBS UI.

### Sunshine ports

- **MVP:** one working Moonlight app (prefer Decky `:47989`).
- **Later:** same launch story on `:48100` / `:48200` if useful. Dual-panel / gamescope-virtual is **out of scope** for Switch capture.

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

**Ship controller MVP at E.** Video starts at F.

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
