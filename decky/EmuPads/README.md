# Emu Pads (Decky)

Always-on mux: virtual **EmuPads P1** (`1209:e301`) and **P2** (`1209:e302`). Every host pad is a source (Sunshine Thor/Odin, phone, tablet, local Xbox, Steam virtual). Cemu / Azahar / Eden bind the sinks. **Apply** changes routing; **Apply and restart** writes binds then SIGTERMs the running emulator and relaunches it (Steam `rungameid` when `SteamAppId` is set). Does not restart the mux or Sunshine.

Install: `scripts/ensure-emupads-mux.sh` then `scripts/ensure-emu-pads-decky.sh`. PluginLoader is root — `main.py` calls `scripts/bind-gamepad.py` as user `deck` (`runuser` + session bus). Never `sudo systemctl --user`. `~/homebrew/plugins` is often `root:root`; copy needs sudo, then reload Decky.

## Routing

- Config: `~/.config/emupads/mux.json`
- **Emu Pads** QAM toggle Off unplugs P1/P2 (`enabled: false`) — the mux process stays up, the uinput nodes disappear. On recreates them (restart Cemu/Azahar/Eden). Mode / dual-screen / Apply writes must keep `enabled`.
- Mute + grab: `$XDG_RUNTIME_DIR/emupads-mute` **or** Steam Home/Library/overlay/QAM (`FOCUSED_APP=769`). Sinks are hidden from Steam (EVIOCGRAB) and from the plugin pad list. Steam still reads the real Sunshine pad.
- **Shared P1** (default): last pad that sent a press or stick is the only one copied (no analog mix).
- **Multi**: first selected → P1, second → P2.
- Skip Steam wrap `28de:11ff` when a Sunshine or physical pad is present (Steam’s curve stacked on SDL made Cemu sticks short). The plugin pad list hides those wraps and the EmuPads sinks — only real host pads (Thor, Odin, physical Xbox, phone) are shown. After Moonlight drops, the list is empty until Odin/Thor injects again; Apply still binds EmuPads P1 while the mux is up. Reconnect, then Refresh pads.
- Shared / Multiplayer writes `mux.json` immediately so the 4s status poll cannot flip the toggle back.
- Emulator **dual-screen** Auto / Dual-screen / HDMI only lives in Decky **Second Screen** (`mux.json` `dual_screen`).
- Axes rescale to the sink ±32767 range.
- Do not list sinks as sources. Do not bind emulators to Sunshine pads. If the mux is down, start it — no fallback.

After `systemctl --user restart emupads-mux.service`, restart Cemu / Azahar / Eden (new uinput nodes).

## Emulators

- **Cemu** P1 type is GamePad when the second screen is streamed, Pro for a local HDMI-only tile (`component_launcher.sh --cemu-p1`). The plugin GamePad/Pro toggle is **Cemu-only** and the next Cemu tile overwrites it.
- **Azahar** has no GamePad/Pro type. Every launch binds standalone `org.azahar_emu.Azahar` and RetroDECK `net.retrodeck.retrodeck` INIs to P1.
- **Eden** P1 / P2 use product `e301` / `e302` so GUIDs differ.

Do not hand-edit XML/INI. Skill: `.cursor/skills/bind-controller/SKILL.md`. Checkpoint `checkpoint-2026-09-11-emupads-mux`. Home/Library mute `checkpoint-2026-09-11-steam-menu-mute`.
