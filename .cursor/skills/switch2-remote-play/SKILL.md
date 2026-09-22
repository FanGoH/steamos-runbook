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

## Status (2026-09-21 → 2026-09-22)

- Skill decisions locked (Decky first, then Game Mode DS; one console; no-touch existing stack).
- **NUXBT** works on **lab** (Pi): demo finished; Switch 2 accepted emulated Pro Controller.
- **NUXBT on De-FanGoH fails to pair** so far: adapter advertises, but `hci0` stays `RX … acl:0` (no ACL link).
- Venv must use Distrobox **system** `/usr/bin/python3.12` (`AF_BLUETOOTH`). Host BlueZ override: `scripts/nuxbt-bluez-override.sh`. Run via `scripts/nuxbt-run.sh`.

### Why lab works and De-FanGoH does not (so far)

| | **lab (works)** | **De-FanGoH (no pair)** |
|--|-----------------|-------------------------|
| Radio | Cypress/Broadcom **BCM43438** UART (`hci_uart_bcm`) | MediaTek **MT7922** USB combo WiFi+BT (`btusb` `0e8d:0616`) |
| HCI | BT 5.0, Bus UART | BT 5.3, Bus USB |
| BlueZ | 5.66 (native) | 5.87 (host) + Distrobox Python |
| Proof | After demo: `RX acl=216` `TX acl=1361`; Switch MAC `48:F1:EB:C3:F4:85` in `/var/lib/bluetooth/…/cache` | During all demos: **`acl=0` always** |
| Runtime | Native `~/code/nuxbt/.venv` | Distrobox `steamos-tools` + host D-Bus |

**Not the primary failure mode:** Distrobox D-Bus (adapters list; alias becomes Pro Controller). Protocol is proven on Switch 2 via lab.

**Likely causes (ordered):**
1. **Distrobox cannot raw-HCI `set_class`** → `PermissionError` on `SOCK_RAW` HCI. NXBT leaves Class at **`0x400000`** instead of Pro Controller **`0x002508`**. Phone still sees the *name* “Pro Controller”; Switch cares about CoD. Lab sets CoD natively (observed `0x00002508` during successful demo). Fix: `sudo scripts/nuxbt-set-class.sh` while demo advertises.
2. MediaTek MT7922 quirks vs BCM43438 (secondary if CoD fix is not enough).
3. WiFi/BT coexistence on the same MT7922 die.
4. Range / placement.

**Proven so far:** Phone Bluetooth scan **does** see “Pro Controller” from De-FanGoH while demo runs → RF advertising works; Switch-side rejection / wrong CoD is the gap.

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
- Install / restore: `scripts/ensure-nuxbt.sh` → Distrobox `steamos-tools` + `~/code/nuxbt/.venv`.
- Expect possible needs: Pro Controller alias, MAC prefix spoof (`7C:BB:8A…`), BlueZ agent trust, Grip/Order for first pair / reconnect.
- `scripts/nuxbt-bluez-override.sh enable|disable|status` — **host** tmpfs BlueZ override (`--compat --noplugin=*`). Never `nuxbt toggle` inside Distrobox.

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
