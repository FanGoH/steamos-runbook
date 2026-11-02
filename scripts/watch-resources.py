#!/usr/bin/env python3
"""Sample host RAM / swap / PSI / top RSS and write a self-contained HTML report.

Answers “did this session actually top RAM?” Capacity pressure is MemAvailable,
swap/zram, memory PSI, and earlyoom’s kill line. It does **not** measure DRAM
bandwidth. Desktop Ryzen is dual-channel even with four DIMMs.

Always-on (user systemd, daily jsonl under logs/resources/):

  ./scripts/ensure-watch-resources.sh
  python3 scripts/watch-resources.py report         # HTML, service keeps running
  python3 scripts/watch-resources.py status

One-shot / debug:

  python3 scripts/watch-resources.py start|stop|watch|sample

earlyoom.service already runs, but it only prints a journal line about once an
hour (`-r 3600`). That is not a time series.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

WATCHED = (
    "eden",
    "cemu",
    "azahar",
    "steam",
    "gamescope",
    "sunshine-ds",
    "sunshine-ds-kms",
    "retrodeck",
)
# AppImage comm is often AppRun.wrapped; match cmdline instead.
CMDLINE_LABELS = (
    ("eden", "eden"),
    ("cemu", "cemu"),
    ("azahar", "azahar"),
    ("sunshine-ds-kms", "sunshine-ds-kms"),
    ("sunshine-ds", "sunshine-ds"),
    ("gamescope", "gamescope"),
    ("retrodeck", "retrodeck"),
    ("steam", "steam"),
)
SERVICE_NAME = os.environ.get(
    "WATCH_RESOURCES_SERVICE", "steamos-watch-resources.service"
)
CHART_POINTS = 720
KEEP_DAYS_DEFAULT = 14
ROLLING_INTERVAL_DEFAULT = 5.0


def proc_root() -> Path:
    return Path(os.environ.get("WATCH_RESOURCES_PROC", "/proc"))


def sys_root() -> Path:
    return Path(os.environ.get("WATCH_RESOURCES_SYS", "/sys"))


def playbook_root() -> Path:
    env = os.environ.get("STEAMOS_PLAYBOOK_DIR")
    here = Path(__file__).resolve().parent.parent
    if env:
        return Path(env)
    return here


def runtime_dir() -> Path:
    env = os.environ.get("WATCH_RESOURCES_RUNTIME")
    if env:
        path = Path(env)
        path.mkdir(parents=True, exist_ok=True)
        return path
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        path = Path(xdg)
        path.mkdir(parents=True, exist_ok=True)
        return path
    path = Path(f"/run/user/{os.getuid()}")
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        fallback = Path("/tmp") / f"watch-resources-{os.getuid()}"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def out_dir() -> Path:
    env = os.environ.get("WATCH_RESOURCES_OUT")
    if env:
        path = Path(env)
    else:
        path = playbook_root() / "logs" / "resources"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pid_path() -> Path:
    return runtime_dir() / "watch-resources.pid"


def session_path() -> Path:
    return runtime_dir() / "watch-resources.session"


def daily_jsonl(when: float | None = None) -> Path:
    stamp = time.strftime("%Y%m%d", time.localtime(when or time.time()))
    return out_dir() / f"{stamp}.jsonl"


def prune_old(keep_days: int = KEEP_DAYS_DEFAULT) -> list[str]:
    removed: list[str] = []
    cutoff = time.strftime(
        "%Y%m%d", time.localtime(time.time() - max(1, keep_days) * 86400)
    )
    for p in out_dir().glob("*"):
        if p.suffix not in {".jsonl", ".html", ".json"} and p.name != "latest.html":
            continue
        stem = p.name[:8]
        if stem.isdigit() and stem < cutoff:
            try:
                p.unlink()
                removed.append(p.name)
            except OSError:
                continue
    return removed


def downsample_series(
    ys: list[float], max_points: int = CHART_POINTS, how: str = "max"
) -> list[float]:
    n = len(ys)
    if n <= max_points or max_points < 2:
        return list(ys)
    out: list[float] = []
    for i in range(max_points):
        a = int(i * n / max_points)
        b = max(a + 1, int((i + 1) * n / max_points))
        chunk = ys[a:b]
        if not chunk:
            chunk = [ys[min(a, n - 1)]]
        if how == "min":
            out.append(min(chunk))
        elif how == "last":
            out.append(chunk[-1])
        else:
            out.append(max(chunk))
    return out


def systemd_cmd(*args: str):
    import subprocess

    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault(
        "DBUS_SESSION_BUS_ADDRESS", f"unix:path={env['XDG_RUNTIME_DIR']}/bus"
    )
    return subprocess.run(
        ["systemctl", "--user", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def systemd_unit_path() -> Path:
    return Path.home() / ".config/systemd/user" / SERVICE_NAME


def service_active() -> bool:
    try:
        return systemd_cmd("is-active", "--quiet", SERVICE_NAME).returncode == 0
    except OSError:
        return False


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def parse_meminfo(text: str | None = None) -> dict[str, int]:
    raw = text if text is not None else _read(proc_root() / "meminfo")
    out: dict[str, int] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        num = rest.strip().split()[0]
        try:
            out[key] = int(num)
        except ValueError:
            continue
    return out


def parse_pressure(text: str | None = None) -> dict[str, float]:
    raw = text if text is not None else _read(proc_root() / "pressure" / "memory")
    out = {
        "some_avg10": 0.0,
        "some_avg60": 0.0,
        "some_avg300": 0.0,
        "some_total": 0.0,
        "full_avg10": 0.0,
        "full_avg60": 0.0,
        "full_avg300": 0.0,
        "full_total": 0.0,
    }
    for line in raw.splitlines():
        parts = line.split()
        if not parts:
            continue
        kind = parts[0]
        if kind not in ("some", "full"):
            continue
        for tok in parts[1:]:
            if "=" not in tok:
                continue
            k, v = tok.split("=", 1)
            try:
                out[f"{kind}_{k}"] = float(v)
            except ValueError:
                continue
    return out


def parse_vmstat(text: str | None = None) -> dict[str, int]:
    raw = text if text is not None else _read(proc_root() / "vmstat")
    want = ("pgmajfault", "pgscan_kswapd", "pgscan_direct", "pswpin", "pswpout")
    out = {k: 0 for k in want}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) != 2 or parts[0] not in out:
            continue
        try:
            out[parts[0]] = int(parts[1])
        except ValueError:
            continue
    return out


def parse_zram_mm_stat(text: str | None = None) -> dict[str, int]:
    raw = text if text is not None else _read(sys_root() / "block" / "zram0" / "mm_stat")
    parts = raw.split()
    nums: list[int] = []
    for p in parts:
        try:
            nums.append(int(p))
        except ValueError:
            nums.append(0)
    orig = nums[0] if len(nums) > 0 else 0
    comp = nums[1] if len(nums) > 1 else 0
    mem = nums[2] if len(nums) > 2 else 0
    return {
        "zram_orig_kib": orig // 1024,
        "zram_comp_kib": comp // 1024,
        "zram_mem_kib": mem // 1024,
    }


def parse_loadavg(text: str | None = None) -> float:
    raw = text if text is not None else _read(proc_root() / "loadavg")
    try:
        return float(raw.split()[0])
    except (IndexError, ValueError):
        return 0.0


def parse_earlyoom_argv(argv: list[str] | None = None) -> dict[str, int]:
    """SteamOS uses -M SIZE,KILL_SIZE in KiB (available RAM)."""
    if argv is None:
        argv = []
        for pid_dir in _pid_dirs():
            if _comm(pid_dir) != "earlyoom":
                continue
            argv = _cmdline(pid_dir).split()
            break
    notify = 0
    kill = 0
    args = argv[1:] if argv and argv[0].endswith("earlyoom") else argv
    i = 0
    while i < len(args):
        if args[i] == "-M" and i + 1 < len(args):
            bits = args[i + 1].split(",")
            try:
                notify = int(bits[0])
                kill = int(bits[1]) if len(bits) > 1 else notify // 2
            except ValueError:
                pass
            i += 2
            continue
        i += 1
    return {"earlyoom_notify_kib": notify, "earlyoom_kill_kib": kill}


def _pid_dirs() -> list[Path]:
    out: list[Path] = []
    try:
        names = os.listdir(proc_root())
    except OSError:
        return out
    for name in names:
        if not name.isdigit():
            continue
        out.append(proc_root() / name)
    return out


def _comm(pid_dir: Path) -> str:
    return _read(pid_dir / "comm").strip()


def _cmdline(pid_dir: Path) -> str:
    raw = (pid_dir / "cmdline").read_bytes() if (pid_dir / "cmdline").is_file() else b""
    return raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()


def _status_kib(pid_dir: Path, key: str) -> int:
    for line in _read(pid_dir / "status").splitlines():
        if line.startswith(key + ":"):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return 0
    return 0


def label_proc(comm: str, cmdline: str) -> str:
    c = comm.lower()
    cl = cmdline.lower()
    if c in ("sunshine-ds", "sunshine-ds-kms"):
        return c
    for needle, label in CMDLINE_LABELS:
        if needle in c or needle in cl:
            return label
    if c == "apprun.wrapped" and "eden" in cl:
        return "eden"
    return comm[:32] or "?"


def collect_top(limit: int = 8) -> list[dict[str, Any]]:
    by_label: dict[str, dict[str, Any]] = {}
    for pid_dir in _pid_dirs():
        comm = _comm(pid_dir)
        if not comm:
            continue
        cmdline = _cmdline(pid_dir)
        rss = _status_kib(pid_dir, "VmRSS")
        if rss <= 0:
            continue
        swap = _status_kib(pid_dir, "VmSwap")
        label = label_proc(comm, cmdline)
        slot = by_label.get(label)
        if slot is None:
            by_label[label] = {
                "pid": int(pid_dir.name),
                "comm": comm,
                "label": label,
                "rss_kib": rss,
                "swap_kib": swap,
                "_peak": rss,
            }
            continue
        slot["rss_kib"] += rss
        slot["swap_kib"] += swap
        if rss > int(slot["_peak"]):
            slot["_peak"] = rss
            slot["pid"] = int(pid_dir.name)
            slot["comm"] = comm
    for slot in by_label.values():
        slot.pop("_peak", None)
    rows = sorted(by_label.values(), key=lambda r: r["rss_kib"], reverse=True)
    picked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in WATCHED:
        row = by_label.get(name)
        if row is None:
            continue
        picked.append(row)
        seen.add(name)
    for row in rows:
        if row["label"] in seen:
            continue
        picked.append(row)
        seen.add(row["label"])
        if len(picked) >= limit:
            break
    picked.sort(key=lambda r: r["rss_kib"], reverse=True)
    return picked[:limit]


def vram_kib() -> dict[str, int]:
    used = 0
    total = 0
    drm = sys_root() / "class" / "drm"
    try:
        cards = sorted(drm.glob("card*"))
    except OSError:
        cards = []
    for card in cards:
        if "-" in card.name:
            continue
        u = _read(card / "device" / "mem_info_vram_used")
        t = _read(card / "device" / "mem_info_vram_total")
        try:
            u_kib = int(u.strip()) // 1024
            t_kib = int(t.strip()) // 1024
        except ValueError:
            continue
        if t_kib > total:
            total = t_kib
            used = u_kib
    return {"vram_used_kib": used, "vram_total_kib": total}


def cpu_model() -> str:
    for line in _read(proc_root() / "cpuinfo").splitlines():
        if line.lower().startswith("model name"):
            return line.split(":", 1)[-1].strip()
    return ""


def board_name() -> str:
    name = _read(sys_root() / "class" / "dmi" / "id" / "board_name").strip()
    vendor = _read(sys_root() / "class" / "dmi" / "id" / "board_vendor").strip()
    return " ".join(p for p in (vendor, name) if p)


def channel_note(cpu: str) -> str:
    low = cpu.lower()
    if "threadripper" in low or "epyc" in low:
        return (
            "This CPU can use four or more memory channels. Populate every "
            "channel if the goal is bandwidth, not only capacity."
        )
    if "ryzen" in low:
        return (
            "Desktop Ryzen is dual-channel DDR5. Four DIMMs still share two "
            "channels (2 DPC). 32 GB here is extra capacity, not four-channel "
            "bandwidth. This trace cannot prove a bandwidth win."
        )
    return (
        "This report measures capacity pressure (available RAM, swap, PSI), "
        "not DRAM bandwidth."
    )


def hardware_snapshot() -> dict[str, Any]:
    mem = parse_meminfo()
    oom = parse_earlyoom_argv()
    cpu = cpu_model()
    vram = vram_kib()
    return {
        "cpu": cpu,
        "board": board_name(),
        "mem_total_kib": mem.get("MemTotal", 0),
        "swap_total_kib": mem.get("SwapTotal", 0),
        "channel_note": channel_note(cpu),
        **oom,
        **vram,
    }


def take_sample(prev_vm: dict[str, int] | None = None) -> dict[str, Any]:
    mem = parse_meminfo()
    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", 0)
    swap_total = mem.get("SwapTotal", 0)
    swap_free = mem.get("SwapFree", 0)
    psi = parse_pressure()
    vm = parse_vmstat()
    zram = parse_zram_mm_stat()
    vram = vram_kib()
    delta = {}
    if prev_vm:
        for k, v in vm.items():
            delta[f"d_{k}"] = max(0, v - prev_vm.get(k, v))
    now = time.time()
    return {
        "t": round(now, 3),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
        "mem_total_kib": total,
        "mem_available_kib": available,
        "mem_used_kib": max(0, total - available),
        "swap_used_kib": max(0, swap_total - swap_free),
        "swap_total_kib": swap_total,
        **zram,
        "psi_some_avg10": psi["some_avg10"],
        "psi_full_avg10": psi["full_avg10"],
        "psi_some_total": psi["some_total"],
        "psi_full_total": psi["full_total"],
        "load1": parse_loadavg(),
        **vm,
        **delta,
        **vram,
        "top": collect_top(),
    }


def kib_g(kib: int | float) -> str:
    return f"{kib / (1024 * 1024):.2f} GiB"


def kib_m(kib: int | float) -> str:
    if kib >= 1024 * 1024:
        return kib_g(kib)
    return f"{kib / 1024:.0f} MiB"


def summarize(samples: list[dict[str, Any]], host: dict[str, Any]) -> dict[str, Any]:
    if not samples:
        return {
            "verdict": "no-data",
            "headline": "No samples yet.",
            "why": "Start the watcher, play a session, then stop.",
            "capacity": "unknown",
        }
    total = host.get("mem_total_kib") or samples[0].get("mem_total_kib") or 1
    used = [s.get("mem_used_kib") or 0 for s in samples]
    avail = [s.get("mem_available_kib") or 0 for s in samples]
    swap = [s.get("swap_used_kib") or 0 for s in samples]
    psi_some = [float(s.get("psi_some_avg10") or 0) for s in samples]
    psi_full = [float(s.get("psi_full_avg10") or 0) for s in samples]
    zram_orig = [s.get("zram_orig_kib") or 0 for s in samples]
    peak_used = max(used)
    min_avail = min(avail)
    peak_swap = max(swap)
    peak_psi = max(psi_some)
    peak_full = max(psi_full)
    peak_zram = max(zram_orig)
    used_pct = 100.0 * peak_used / total if total else 0.0
    notify = int(host.get("earlyoom_notify_kib") or 0)
    kill = int(host.get("earlyoom_kill_kib") or 0)
    line = kill or notify
    peaks: dict[str, int] = {}
    for s in samples:
        for row in s.get("top") or []:
            label = str(row.get("label") or row.get("comm") or "?")
            rss = int(row.get("rss_kib") or 0)
            if rss > peaks.get(label, 0):
                peaks[label] = rss
    topped = False
    close = False
    reasons: list[str] = []
    low_avail = min_avail <= 2 * 1024 * 1024
    if line and min_avail <= line:
        topped = True
        reasons.append(
            f"MemAvailable bottomed at {kib_m(min_avail)}, at or below earlyoom "
            f"({kib_m(line)})."
        )
    elif line and min_avail <= line * 2:
        close = True
        reasons.append(
            f"MemAvailable bottomed at {kib_m(min_avail)} (earlyoom line "
            f"{kib_m(line)})."
        )
    elif low_avail:
        close = True
        reasons.append(f"MemAvailable bottomed at {kib_m(min_avail)}.")
    # Swap/zram only counts as capacity pressure when RAM is also scarce.
    # Idle zram leftovers with 10 GiB available are not “topped”.
    if low_avail and peak_swap >= 1024 * 1024:
        topped = True
        reasons.append(f"Swap peaked at {kib_m(peak_swap)} while RAM was scarce.")
    elif low_avail and peak_swap >= 256 * 1024:
        close = True
        reasons.append(f"Swap climbed to {kib_m(peak_swap)} while RAM was scarce.")
    if low_avail and peak_zram >= 512 * 1024:
        close = True
        reasons.append(
            f"zram stored {kib_m(peak_zram)} uncompressed while RAM was scarce. "
            "zram is compressed RAM, not extra capacity."
        )
    if peak_full >= 0.1:
        topped = True
        reasons.append(f"Memory PSI full avg10 peaked at {peak_full:.2f} (stalled).")
    elif peak_psi >= 1.0:
        close = True
        reasons.append(f"Memory PSI some avg10 peaked at {peak_psi:.2f}.")
    if used_pct >= 90:
        close = True
        reasons.append(f"Peak used was {used_pct:.0f}% of {kib_g(total)}.")
    if topped:
        capacity = "topped"
        headline = "This session topped RAM. More GB would help."
    elif close:
        capacity = "close"
        headline = "This session ran close. 32 GB would add headroom."
    else:
        capacity = "headroom"
        headline = "This session did not top RAM."
        reasons.append(
            f"Lowest MemAvailable was {kib_m(min_avail)} of {kib_g(total)} "
            f"({100.0 * min_avail / total:.0f}% free-ish). Peak used "
            f"{kib_g(peak_used)}."
        )
    return {
        "verdict": capacity,
        "capacity": capacity,
        "headline": headline,
        "why": " ".join(reasons),
        "peak_used_kib": peak_used,
        "min_available_kib": min_avail,
        "peak_swap_kib": peak_swap,
        "peak_zram_orig_kib": peak_zram,
        "peak_psi_some": peak_psi,
        "peak_psi_full": peak_full,
        "used_pct": round(used_pct, 1),
        "samples": len(samples),
        "started": samples[0].get("iso"),
        "ended": samples[-1].get("iso"),
        "duration_s": round(
            float(samples[-1].get("t") or 0) - float(samples[0].get("t") or 0), 1
        ),
        "process_peaks_kib": peaks,
        "earlyoom_notify_kib": notify,
        "earlyoom_kill_kib": kill,
        "channel_note": host.get("channel_note") or channel_note(host.get("cpu") or ""),
    }


def _svg_polyline(
    ys: list[float],
    *,
    y_max: float,
    width: int = 760,
    height: int = 180,
    color: str = "#7eb8ff",
) -> str:
    if not ys:
        return ""
    pad_l, pad_r, pad_t, pad_b = 44, 12, 12, 24
    inner_w = max(1, width - pad_l - pad_r)
    inner_h = max(1, height - pad_t - pad_b)
    ceiling = y_max if y_max > 0 else 1.0
    n = len(ys)
    pts: list[str] = []
    for i, y in enumerate(ys):
        x = pad_l + (inner_w * i / max(1, n - 1))
        yy = pad_t + inner_h * (1.0 - min(1.0, max(0.0, y / ceiling)))
        pts.append(f"{x:.1f},{yy:.1f}")
    return (
        f'<polyline fill="none" stroke="{color}" stroke-width="2" '
        f'points="{" ".join(pts)}"/>'
    )


def svg_chart(
    series: list[tuple[str, str, list[float]]],
    *,
    y_max: float,
    y_unit: str,
    hlines: list[tuple[float, str, str]] | None = None,
    width: int = 760,
    height: int = 180,
) -> str:
    pad_l, pad_r, pad_t, pad_b = 44, 12, 12, 24
    inner_h = max(1, height - pad_t - pad_b)
    ceiling = y_max if y_max > 0 else 1.0
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img">'
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="8" fill="#161b22"/>'
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{height - pad_b}" '
        f'stroke="#30363d"/>'
        f'<line x1="{pad_l}" y1="{height - pad_b}" x2="{width - pad_r}" '
        f'y2="{height - pad_b}" stroke="#30363d"/>'
        f'<text x="8" y="{pad_t + 10}" fill="#8b949e" font-size="11">'
        f"{ceiling:g}{y_unit}</text>"
        f'<text x="8" y="{height - pad_b}" fill="#8b949e" font-size="11">0</text>'
    ]
    for y, color, label in hlines or []:
        if y <= 0 or y > ceiling:
            continue
        yy = pad_t + inner_h * (1.0 - y / ceiling)
        parts.append(
            f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{width - pad_r}" y2="{yy:.1f}" '
            f'stroke="{color}" stroke-dasharray="4 4" stroke-width="1"/>'
            f'<text x="{pad_l + 6}" y="{yy - 4:.1f}" fill="{color}" font-size="10">'
            f"{label}</text>"
        )
    for _name, color, ys in series:
        parts.append(_svg_polyline(ys, y_max=ceiling, width=width, height=height, color=color))
    lx = pad_l
    for name, color, _ys in series:
        parts.append(
            f'<rect x="{lx}" y="{height - 16}" width="8" height="8" fill="{color}"/>'
            f'<text x="{lx + 12}" y="{height - 9}" fill="#c9d1d9" font-size="11">'
            f"{name}</text>"
        )
        lx += 12 + 7 * len(name) + 16
    parts.append("</svg>")
    return "".join(parts)


def _series_for(samples: list[dict[str, Any]], key: str) -> list[float]:
    return [float(s.get(key) or 0) for s in samples]


def _label_series(samples: list[dict[str, Any]], label: str) -> list[float]:
    out: list[float] = []
    for s in samples:
        rss = 0
        for row in s.get("top") or []:
            if row.get("label") == label:
                rss = max(rss, int(row.get("rss_kib") or 0))
        out.append(float(rss))
    return out


def render_html(
    samples: list[dict[str, Any]],
    host: dict[str, Any],
    summary: dict[str, Any] | None = None,
) -> str:
    summary = summary or summarize(samples, host)
    verdict = summary.get("capacity") or "unknown"
    colors = {
        "topped": "#f85149",
        "close": "#d29922",
        "headroom": "#3fb950",
        "no-data": "#8b949e",
        "unknown": "#8b949e",
    }
    accent = colors.get(verdict, "#8b949e")
    used_gib = downsample_series(
        [v / (1024 * 1024) for v in _series_for(samples, "mem_used_kib")], how="max"
    )
    avail_gib = downsample_series(
        [v / (1024 * 1024) for v in _series_for(samples, "mem_available_kib")], how="min"
    )
    swap_mib = downsample_series(
        [v / 1024 for v in _series_for(samples, "swap_used_kib")], how="max"
    )
    zram_mib = downsample_series(
        [v / 1024 for v in _series_for(samples, "zram_orig_kib")], how="max"
    )
    psi_some = downsample_series(_series_for(samples, "psi_some_avg10"), how="max")
    psi_full = downsample_series(_series_for(samples, "psi_full_avg10"), how="max")
    vram_gib = downsample_series(
        [v / (1024 * 1024) for v in _series_for(samples, "vram_used_kib")], how="max"
    )
    total_gib = (host.get("mem_total_kib") or 0) / (1024 * 1024)
    kill_gib = (host.get("earlyoom_kill_kib") or 0) / (1024 * 1024)
    notify_gib = (host.get("earlyoom_notify_kib") or 0) / (1024 * 1024)
    ram_chart = svg_chart(
        [
            ("used (total−available)", "#58a6ff", used_gib),
            ("available", "#3fb950", avail_gib),
        ],
        y_max=max(total_gib, 1.0),
        y_unit="G",
        hlines=[
            (total_gib, "#8b949e", f"total {total_gib:.1f}G"),
            (notify_gib, "#d29922", "earlyoom SIGTERM") if notify_gib else (0, "", ""),
            (kill_gib, "#f85149", "earlyoom SIGKILL") if kill_gib else (0, "", ""),
        ],
    )
    swap_max = max([1.0, *swap_mib, *zram_mib])
    swap_chart = svg_chart(
        [
            ("swap used", "#f778ba", swap_mib),
            ("zram orig", "#a371f7", zram_mib),
        ],
        y_max=swap_max,
        y_unit="M",
    )
    psi_max = max([1.0, *psi_some, *psi_full])
    psi_chart = svg_chart(
        [
            ("PSI some avg10", "#d29922", psi_some),
            ("PSI full avg10", "#f85149", psi_full),
        ],
        y_max=psi_max,
        y_unit="",
    )
    proc_series: list[tuple[str, str, list[float]]] = []
    palette = ("#ff7b72", "#79c0ff", "#d2a8ff", "#7ee787", "#ffa657", "#f778ba")
    peaks = summary.get("process_peaks_kib") or {}
    interesting = [n for n in WATCHED if (peaks.get(n) or 0) > 0]
    if not interesting:
        interesting = sorted(peaks, key=lambda k: peaks[k], reverse=True)[:4]
    for i, name in enumerate(interesting[:6]):
        ys = downsample_series(
            [v / (1024 * 1024) for v in _label_series(samples, name)], how="max"
        )
        proc_series.append((name, palette[i % len(palette)], ys))
    proc_max = max([0.5, *(max(ys) if ys else 0 for _n, _c, ys in proc_series)])
    proc_chart = svg_chart(proc_series, y_max=proc_max, y_unit="G") if proc_series else ""
    vram_total = (host.get("vram_total_kib") or 0) / (1024 * 1024)
    vram_chart = ""
    if vram_total > 0 and any(vram_gib):
        vram_chart = svg_chart(
            [("VRAM used", "#58a6ff", vram_gib)],
            y_max=max(vram_total, 1.0),
            y_unit="G",
            hlines=[(vram_total, "#8b949e", f"total {vram_total:.1f}G")],
        )
    peak_rows = "".join(
        f"<tr><td>{name}</td><td>{kib_g(kib)}</td></tr>"
        for name, kib in sorted(peaks.items(), key=lambda kv: kv[1], reverse=True)
        if kib > 0
    )
    cards = [
        ("Peak used", kib_g(summary.get("peak_used_kib") or 0)),
        ("Min available", kib_g(summary.get("min_available_kib") or 0)),
        ("Peak swap", kib_m(summary.get("peak_swap_kib") or 0)),
        ("Peak PSI some", f"{float(summary.get('peak_psi_some') or 0):.2f}"),
        ("Samples", str(summary.get("samples") or 0)),
        ("Duration", f"{float(summary.get('duration_s') or 0):.0f}s"),
    ]
    card_html = "".join(
        f'<div class="card"><div class="k">{k}</div><div class="v">{v}</div></div>'
        for k, v in cards
    )
    vram_block = (
        f"<h2>GPU VRAM</h2><div class='chart'>{vram_chart}</div>" if vram_chart else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RAM session {summary.get("started") or ""}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{
    margin: 0; font: 15px/1.45 ui-sans-serif, system-ui, sans-serif;
    background: #0d1117; color: #c9d1d9;
  }}
  main {{ max-width: 820px; margin: 0 auto; padding: 28px 20px 64px; }}
  h1 {{ font-size: 22px; margin: 0 0 6px; color: #f0f6fc; }}
  h2 {{ font-size: 16px; margin: 28px 0 10px; color: #f0f6fc; }}
  .meta {{ color: #8b949e; margin: 0 0 18px; }}
  .verdict {{
    border: 1px solid {accent}; background: #161b22; border-radius: 12px;
    padding: 16px 18px; margin: 16px 0 22px;
  }}
  .verdict h2 {{ margin: 0 0 8px; color: {accent}; font-size: 18px; }}
  .verdict p {{ margin: 0 0 8px; }}
  .note {{ color: #8b949e; font-size: 13px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 10px; margin: 12px 0 8px; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 10px;
           padding: 12px; }}
  .card .k {{ color: #8b949e; font-size: 12px; }}
  .card .v {{ font-size: 18px; color: #f0f6fc; margin-top: 4px; }}
  .chart {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; }}
  td, th {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #21262d; }}
  th {{ color: #8b949e; font-weight: 600; }}
  .host {{ color: #8b949e; font-size: 13px; }}
</style>
</head>
<body>
<main>
  <h1>Resource session</h1>
  <p class="meta">{summary.get("started") or "—"} → {summary.get("ended") or "—"}
    · {host.get("cpu") or "cpu?"}
    · {kib_g(host.get("mem_total_kib") or 0)} RAM</p>
  <section class="verdict">
    <h2>{summary.get("headline")}</h2>
    <p>{summary.get("why")}</p>
    <p class="note">{summary.get("channel_note")}</p>
  </section>
  <div class="cards">{card_html}</div>
  <p class="host">{host.get("board") or ""}
    · earlyoom notify {kib_m(host.get("earlyoom_notify_kib") or 0) if host.get("earlyoom_notify_kib") else "n/a"}
    / kill {kib_m(host.get("earlyoom_kill_kib") or 0) if host.get("earlyoom_kill_kib") else "n/a"}</p>
  <h2>Host RAM</h2>
  <div class="chart">{ram_chart}</div>
  <h2>Swap / zram</h2>
  <p class="note">zram is compressed RAM, not a free dump buffer. Climbing zram
    while MemAvailable falls means the box is already in pressure.</p>
  <div class="chart">{swap_chart}</div>
  <h2>Memory stall (PSI)</h2>
  <p class="note">Non-zero <code>full</code> means tasks sat waiting on reclaim.
    That is a stronger “topped” signal than a high RSS number.</p>
  <div class="chart">{psi_chart}</div>
  <h2>Process RSS</h2>
  <div class="chart">{proc_chart}</div>
  {vram_block}
  <h2>Peak RSS by label</h2>
  <table>
    <thead><tr><th>process</th><th>peak RSS</th></tr></thead>
    <tbody>{peak_rows or "<tr><td colspan='2'>none</td></tr>"}</tbody>
  </table>
</main>
</body>
</html>
"""


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    if not path.is_file():
        return samples
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and "t" in row:
            samples.append(row)
    return samples


def latest_jsonl() -> Path | None:
    daily = daily_jsonl()
    if daily.is_file():
        return daily
    files = sorted(out_dir().glob("*.jsonl"))
    return files[-1] if files else None


def load_recent(hours: float) -> tuple[list[dict[str, Any]], list[Path]]:
    cutoff = time.time() - max(0.1, hours) * 3600
    paths = sorted(out_dir().glob("*.jsonl"))
    samples: list[dict[str, Any]] = []
    used: list[Path] = []
    for path in paths:
        rows = [s for s in load_jsonl(path) if float(s.get("t") or 0) >= cutoff]
        if rows:
            samples.extend(rows)
            used.append(path)
    samples.sort(key=lambda s: float(s.get("t") or 0))
    return samples, used


def write_report(
    jsonl: Path | None = None,
    host: dict[str, Any] | None = None,
    samples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    path = jsonl or latest_jsonl()
    if samples is None:
        if path is None:
            return {"ok": False, "message": "no resource sessions in logs/resources"}
        samples = load_jsonl(path)
        meta_path = path.with_suffix(".meta.json")
        meta = {}
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {}
        host = host or meta.get("host") or hardware_snapshot()
    else:
        host = host or hardware_snapshot()
        path = path or daily_jsonl()
    summary = summarize(samples, host)
    html = render_html(samples, host, summary)
    html_path = path.with_suffix(".html") if path else out_dir() / "latest.html"
    html_path.write_text(html, encoding="utf-8")
    latest = out_dir() / "latest.html"
    try:
        if latest.is_symlink() or latest.is_file():
            latest.unlink()
        if html_path.resolve() != latest.resolve():
            latest.symlink_to(html_path.name)
        else:
            latest.write_text(html, encoding="utf-8")
    except OSError:
        latest.write_text(html, encoding="utf-8")
    summary["html"] = str(html_path)
    summary["jsonl"] = str(path) if path else None
    summary["ok"] = True
    return summary


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_session() -> dict[str, Any]:
    raw = _read(session_path())
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_session(data: dict[str, Any]) -> None:
    session_path().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def running_pid() -> int | None:
    raw = _read(pid_path()).strip()
    if not raw.isdigit():
        return None
    pid = int(raw)
    if not _alive(pid):
        return None
    proc_pid = proc_root() / str(pid)
    cmdline = _cmdline(proc_pid) if proc_pid.is_dir() else ""
    comm = _comm(proc_pid) if proc_pid.is_dir() else ""
    if "watch-resources" not in cmdline and "watch-resources" not in comm:
        if str(proc_root()) == "/proc":
            return None
    return pid


def cmd_sample() -> int:
    print(json.dumps(take_sample(), indent=2))
    return 0


def cmd_status() -> int:
    pid = running_pid()
    active = service_active()
    sess = read_session()
    jsonl = Path(sess["jsonl"]) if sess.get("jsonl") else latest_jsonl()
    samples = load_jsonl(jsonl) if jsonl else []
    data = {
        "ok": True,
        "running": bool(pid) or active,
        "service": SERVICE_NAME,
        "service_active": active,
        "pid": pid,
        "session": sess.get("session"),
        "jsonl": str(jsonl) if jsonl else None,
        "html": str(out_dir() / "latest.html")
        if (out_dir() / "latest.html").exists()
        else sess.get("html"),
        "samples": len(samples),
        "host": sess.get("host") or hardware_snapshot(),
    }
    if samples:
        data["summary"] = summarize(samples, data["host"])
    print(json.dumps(data, indent=2))
    return 0


def cmd_watch(
    interval: float,
    duration: float,
    jsonl: Path | None,
    rolling: bool = False,
    keep_days: int = KEEP_DAYS_DEFAULT,
) -> int:
    host = hardware_snapshot()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = daily_jsonl() if rolling else (jsonl or (out_dir() / f"{stamp}.jsonl"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "session": dest.stem,
        "host": host,
        "interval": interval,
        "jsonl": str(dest),
        "rolling": rolling,
    }
    dest.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    write_session({**meta, "pid": os.getpid(), "html": str(dest.with_suffix(".html"))})
    pid_path().write_text(str(os.getpid()) + "\n", encoding="utf-8")
    stop = {"flag": False}

    def _stop(_signum=None, _frame=None) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    prev_vm = parse_vmstat()
    start = time.time()
    n = 0
    if rolling:
        prune_old(keep_days)
    fh = dest.open("a", encoding="utf-8")
    try:
        while not stop["flag"]:
            if rolling:
                wanted = daily_jsonl()
                if wanted != dest:
                    fh.close()
                    dest = wanted
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    fh = dest.open("a", encoding="utf-8")
                    meta["jsonl"] = str(dest)
                    meta["session"] = dest.stem
                    dest.with_suffix(".meta.json").write_text(
                        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
                    )
                    prune_old(keep_days)
            sample = take_sample(prev_vm)
            prev_vm = {k: int(sample.get(k) or 0) for k in parse_vmstat()}
            fh.write(json.dumps(sample, separators=(",", ":")) + "\n")
            fh.flush()
            n += 1
            if n == 1 or n % 15 == 0:
                sys.stderr.write(
                    f"watch-resources {dest.name} n={n} "
                    f"avail={kib_m(sample['mem_available_kib'])} "
                    f"used={kib_g(sample['mem_used_kib'])}\n"
                )
                sys.stderr.flush()
            if duration > 0 and (time.time() - start) >= duration:
                break
            deadline = time.time() + interval
            while not stop["flag"] and time.time() < deadline:
                time.sleep(min(0.2, deadline - time.time()))
    finally:
        fh.close()
    if rolling:
        sys.stderr.write(f"watch-resources stopped jsonl={dest}\n")
    else:
        print(json.dumps(write_report(dest, host), indent=2))
    try:
        pid_path().unlink(missing_ok=True)
    except OSError:
        pass
    return 0


def cmd_start(interval: float, duration: float) -> int:
    if duration <= 0 and systemd_unit_path().is_file():
        if service_active():
            print(
                json.dumps(
                    {
                        "ok": True,
                        "running": True,
                        "service": SERVICE_NAME,
                        "jsonl": str(daily_jsonl()),
                        "html": str(out_dir() / "latest.html"),
                        "message": f"{SERVICE_NAME} already active. fgpc host ram report",
                    },
                    indent=2,
                )
            )
            return 0
        got = systemd_cmd("start", SERVICE_NAME)
        if got.returncode != 0:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "message": (got.stderr or got.stdout or "systemctl start failed").strip(),
                        "service": SERVICE_NAME,
                    },
                    indent=2,
                )
            )
            return 2
        print(
            json.dumps(
                {
                    "ok": True,
                    "running": True,
                    "service": SERVICE_NAME,
                    "jsonl": str(daily_jsonl()),
                    "message": f"Started {SERVICE_NAME}. Play; then fgpc host ram report",
                },
                indent=2,
            )
        )
        return 0
    existing = running_pid()
    if existing:
        print(json.dumps({"ok": False, "message": f"already running pid={existing}", "pid": existing}))
        return 2
    stamp = time.strftime("%Y%m%d-%H%M%S")
    jsonl = out_dir() / f"{stamp}.jsonl"
    log = out_dir() / "watch.log"
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "watch",
        "--interval",
        str(interval),
        "--jsonl",
        str(jsonl),
    ]
    if duration > 0:
        cmd.extend(["--duration", str(duration)])
    log_fh = log.open("a", encoding="utf-8")
    proc = subprocess_popen(cmd, log_fh)
    write_session(
        {
            "session": stamp,
            "pid": proc.pid,
            "jsonl": str(jsonl),
            "html": str(jsonl.with_suffix(".html")),
            "interval": interval,
            "host": hardware_snapshot(),
        }
    )
    pid_path().write_text(str(proc.pid) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "pid": proc.pid,
                "session": stamp,
                "jsonl": str(jsonl),
                "html": str(jsonl.with_suffix(".html")),
                "log": str(log),
                "interval": interval,
                "message": "Watching. Install the user unit with ./scripts/ensure-watch-resources.sh for always-on.",
            },
            indent=2,
        )
    )
    return 0


def subprocess_popen(cmd: list[str], log_fh: Any):
    import subprocess

    return subprocess.Popen(
        cmd,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=os.environ.copy(),
        cwd=str(playbook_root()),
    )


def cmd_stop() -> int:
    sess = read_session()
    if service_active():
        systemd_cmd("stop", SERVICE_NAME)
    pid = running_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(50):
            if not _alive(pid):
                break
            time.sleep(0.1)
        if _alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    jsonl = Path(sess["jsonl"]) if sess.get("jsonl") else latest_jsonl()
    if not jsonl or not jsonl.is_file():
        print(json.dumps({"ok": False, "message": "no jsonl to report"}))
        return 2
    host = sess.get("host") or hardware_snapshot()
    summary = write_report(jsonl, host)
    try:
        pid_path().unlink(missing_ok=True)
    except OSError:
        pass
    print(json.dumps(summary, indent=2))
    return 0


def cmd_report(jsonl: Path | None, hours: float | None = None) -> int:
    host = hardware_snapshot()
    if jsonl:
        summary = write_report(jsonl, host)
    else:
        window = 24.0 if hours is None else hours
        samples, used = load_recent(window)
        if not samples:
            print(json.dumps({"ok": False, "message": "no resource samples yet"}))
            return 2
        summary = write_report(used[-1] if used else None, host, samples=samples)
        summary["hours"] = window
        summary["files"] = [str(p) for p in used]
    print(json.dumps(summary, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RAM / PSI watcher + HTML")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample", help="One JSON snapshot")
    sub.add_parser("status", help="Is the watcher / user service running?")
    start_p = sub.add_parser("start", help="Start user service, or a one-shot if no unit")
    start_p.add_argument("--interval", type=float, default=ROLLING_INTERVAL_DEFAULT)
    start_p.add_argument("--duration", type=float, default=0.0, help="One-shot seconds")
    sub.add_parser("stop", help="Stop watcher/service and write HTML")
    watch_p = sub.add_parser("watch", help="Foreground loop (systemd ExecStart)")
    watch_p.add_argument("--interval", type=float, default=ROLLING_INTERVAL_DEFAULT)
    watch_p.add_argument("--duration", type=float, default=0.0)
    watch_p.add_argument("--jsonl", type=Path, default=None)
    watch_p.add_argument(
        "--rolling",
        action="store_true",
        help="Daily jsonl + prune (always-on service)",
    )
    watch_p.add_argument("--keep-days", type=int, default=KEEP_DAYS_DEFAULT)
    report_p = sub.add_parser("report", help="Write HTML; does not stop the service")
    report_p.add_argument("--jsonl", type=Path, default=None)
    report_p.add_argument(
        "--hours",
        type=float,
        default=24.0,
        help="How far back to chart (ignored if --jsonl)",
    )
    args = parser.parse_args(argv)
    interval = max(0.5, float(getattr(args, "interval", ROLLING_INTERVAL_DEFAULT) or ROLLING_INTERVAL_DEFAULT))
    duration = max(0.0, float(getattr(args, "duration", 0.0) or 0.0))
    if args.cmd == "sample":
        return cmd_sample()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "start":
        return cmd_start(interval, duration)
    if args.cmd == "stop":
        return cmd_stop()
    if args.cmd == "watch":
        return cmd_watch(
            interval,
            duration,
            args.jsonl,
            rolling=bool(args.rolling),
            keep_days=int(args.keep_days),
        )
    if args.cmd == "report":
        hours = None if args.jsonl else float(args.hours)
        return cmd_report(args.jsonl, hours=hours)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
