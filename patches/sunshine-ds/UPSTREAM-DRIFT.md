# Upstream drift while cherry-picking Sunshine DS onto current main

Base of the original DS series: `cf52f4b` (LizardByte around 2026-08).
Current main used here: `c53f97ec` (~89 commits later).

## Cherry-picks

| Commit | Result |
| --- | --- |
| `5ad68b89` negotiate second stream | Clean |
| `40debf89` second-stream transport | Conflict in `src/stream.cpp` (`video_stream_t` vs anonymous `video` struct). Kept DS named `video`/`video2` and upstream comments. |
| `98eea5d3` second capture/encode | Clean |
| `85b97122` MinHook cmake | Clean |
| `25be3eba` DS dual-display | Conflicts below |

## `25be3eba` conflicts

- `docker/ubuntu-22.04.dockerfile`, `ubuntu-24.04.dockerfile`, `ubuntu-26.04.dockerfile`: deleted upstream. Dropped the DS docker branding on those files.
- `src/stream.cpp`: kept both `IDX_SET_PLAYER_LEDS` (upstream) and `VIDEO_STREAM_FAILURE_REASON` (DS); kept `input_session_id` (libvirtualhid resume) and `client_unique_id` (virtual monitor identity); kept DS `iv_stream_id` and `video2_termination_queue`.
- `src/input.h`: union of includes; DS `CLIENT_DISPLAY_COUNT` / `client_display_index` plus upstream `alloc(mail, session_id)`.
- `src/input.cpp`: kept upstream retained-input / `libvirtualhid` resume path; constructor takes both touch-port events; `prepare_absolute_pointer_data` uses per-display `active_touch_port`; touch `CANCEL_ALL` is scoped per panel.
- `tests/unit/test_stream.cpp`: kept upstream control-packet tests and DS indexed IDR / ref-frame tests.

## Follow-up (not from the fork)

- `0006`/`0008`: Linux KWin virtual output via `sunshine-ds-virtual-output`
  (`zkde_screencast_unstable_v1.stream_virtual_output`). Distrobox `krfb` cannot
  talk to SteamOS KWin; host `krfb` remains an optional fallback.
- `0007`: docs for that path.

PipeWire unpaced capture (`#5629`) and pairing refactors auto-merged into `video.cpp` / `stream.cpp`. Validate dual KWin capture on hardware; that is the remaining risk.
