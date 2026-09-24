const TABS = [
  { id: "stream", label: "Stream" },
  { id: "screen", label: "Screen" },
  { id: "pad", label: "Pad" },
  { id: "hide", label: "Hide" },
  { id: "more", label: "More" },
];

const state = {
  status: null,
  busy: "",
  tab: "stream",
  dual: "auto",
  padMode: "shared",
};

function $(id) {
  return document.getElementById(id);
}

function asList(raw) {
  return Array.isArray(raw) ? raw : [];
}

function toast(ok, text) {
  const el = $("toast");
  el.hidden = !text;
  el.className = `toast ${ok === false ? "bad" : "ok"}`;
  el.textContent = text || "";
}

function streamLine(status) {
  const kms = status?.stream?.gamemode?.message;
  if (kms) return `Game Mode :48200 · ${kms}`;
  if (status?.stream?.note) return status.stream.note;
  return "Game Mode Moonlight is :48200 (not Decky :47989).";
}

function windowLabel(win) {
  const name = win?.name || "(unnamed)";
  const size = `${win?.width || "?"}×${win?.height || "?"}`;
  return `${name} · ${win?.display || "?"} · ${size}`;
}

function padDescription(pad) {
  const bits = [];
  if (pad.kind) bits.push(pad.kind);
  if (pad.usb) bits.push(`usb ${pad.usb}`);
  if (pad.hidden) bits.push(pad.connected ? "hidden" : "unplugged");
  else bits.push("connected");
  if (pad.reason) bits.push(pad.reason);
  return bits.join(" · ");
}

async function refresh() {
  try {
    const next = await fetch("/api/status").then((r) => r.json());
    state.status = next;
    if (next?.ok === false) toast(false, next.message || "status failed");
    const ds = next?.screen?.dual_screen || next?.screen?.dual_screen_live?.mode;
    if (ds === "auto" || ds === "on" || ds === "off") state.dual = ds;
    const mode = next?.pad?.mux?.mode;
    if (mode === "shared" || mode === "multi") state.padMode = mode;
    $("status-line").textContent = streamLine(next);
    render();
  } catch (err) {
    $("status-line").textContent = String(err);
    toast(false, String(err));
  }
}

async function run(title, group, action, extra) {
  if (state.busy) return;
  state.busy = `${group}:${action}`;
  render();
  try {
    const body = Object.assign(
      { group, action, emu: "all", mode: "", pad_id: "", display: "", target: "" },
      extra || {}
    );
    const result = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.json());
    const msg = (result?.messages || [result?.message || ""])
      .filter(Boolean)
      .join(" ")
      .slice(0, 220);
    toast(result?.ok !== false, msg || title);
    await refresh();
  } catch (err) {
    toast(false, String(err).slice(0, 220));
  } finally {
    state.busy = "";
    render();
  }
}

function btn(label, opts) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = label;
  if (opts.on) b.classList.add("on");
  if (opts.danger) b.classList.add("danger");
  b.disabled = Boolean(state.busy) || Boolean(opts.disabled);
  b.addEventListener("click", opts.click);
  return b;
}

function card(title, children) {
  const el = document.createElement("section");
  el.className = "card";
  const h = document.createElement("h2");
  h.textContent = title;
  el.appendChild(h);
  children.forEach((child) => el.appendChild(child));
  return el;
}

function row(cls, children) {
  const el = document.createElement("div");
  el.className = `row ${cls || ""}`.trim();
  children.forEach((child) => el.appendChild(child));
  return el;
}

function note(text) {
  const p = document.createElement("p");
  p.textContent = text;
  return p;
}

function renderStream(root) {
  const s = state.status || {};
  root.appendChild(
    card("Game Mode :48200", [
      note(streamLine(s)),
      row("two", [
        btn(state.busy === "stream:start-kms" ? "Starting…" : "Start kms", {
          click: () => run("Start kms", "stream", "start-kms"),
        }),
        btn("Paint clock", {
          click: () => run("Paint clock", "stream", "paint"),
        }),
        btn("Stop kms", {
          danger: true,
          click: () => run("Stop kms", "stream", "stop"),
        }),
        btn("Close Cemu", {
          click: () => run("Close Cemu", "stream", "close-cemu"),
        }),
        btn("Close Azahar", {
          click: () => run("Close Azahar", "stream", "close-azahar"),
        }),
      ]),
    ])
  );
}

function renderScreen(root) {
  const s = state.status || {};
  const windows = asList(s.screen?.windows);
  const kids = [
    note(
      s.screen?.dual_screen_live?.reason ||
        "Auto: GamePad layout only when Moonlight watches the bottom."
    ),
    row("three", [
      btn(state.dual === "auto" ? "Auto ✓" : "Auto", {
        on: state.dual === "auto",
        click: () => {
          state.dual = "auto";
          run("Auto DS", "screen", "dual", { mode: "auto" });
        },
      }),
      btn(state.dual === "on" ? "Dual ✓" : "Dual", {
        on: state.dual === "on",
        click: () => {
          state.dual = "on";
          run("Dual-screen", "screen", "dual", { mode: "on" });
        },
      }),
      btn(state.dual === "off" ? "HDMI ✓" : "HDMI", {
        on: state.dual === "off",
        click: () => {
          state.dual = "off";
          run("HDMI only", "screen", "dual", { mode: "off" });
        },
      }),
    ]),
    row("", [
      btn("Moonlight Screensaver", {
        click: () => run("Idle clock", "screen", "clock"),
      }),
    ]),
  ];
  if (!windows.length) {
    kids.push(note("No session windows yet. Open a game, then Refresh."));
  }
  windows.forEach((win) => {
    const item = document.createElement("div");
    item.className = "item";
    item.appendChild(note(windowLabel(win)));
    const onBottom = win.display === (s.screen?.pad_display || ":2");
    item.appendChild(
      btn(onBottom ? "Maximize on bottom" : "Show on second screen", {
        click: () =>
          run("Second screen", "screen", "show", {
            pad_id: win.id,
            display: win.display,
          }),
      })
    );
    kids.push(item);
  });
  root.appendChild(card("Second screen", kids));
}

function renderPad(root) {
  const mux = state.status?.pad?.mux || {};
  root.appendChild(
    card("EmuPads", [
      note(
        mux.running
          ? `Mux ${mux.mode || state.padMode} · bind P1/P2`
          : "Mux down. Apply still starts it via bind-gamepad.py."
      ),
      row("choice", [
        btn(state.padMode === "shared" ? "Shared ✓" : "Shared", {
          on: state.padMode === "shared",
          click: () => {
            state.padMode = "shared";
            run("Shared P1", "pad", "mode", { mode: "shared" });
          },
        }),
        btn(state.padMode === "multi" ? "Multi ✓" : "Multi", {
          on: state.padMode === "multi",
          click: () => {
            state.padMode = "multi";
            run("Multi P1+P2", "pad", "mode", { mode: "multi" });
          },
        }),
      ]),
      row("two", [
        btn(state.busy === "pad:apply" ? "Applying…" : "Apply all", {
          click: () =>
            run("Apply binds", "pad", "apply", {
              emu: "all",
              mode: state.padMode,
            }),
        }),
        btn("Cemu", {
          click: () =>
            run("Apply Cemu", "pad", "apply", {
              emu: "cemu",
              mode: state.padMode,
            }),
        }),
        btn("Azahar", {
          click: () =>
            run("Apply Azahar", "pad", "apply", {
              emu: "azahar",
              mode: state.padMode,
            }),
        }),
        btn("Eden", {
          click: () =>
            run("Apply Eden", "pad", "apply", {
              emu: "eden",
              mode: state.padMode,
            }),
        }),
      ]),
    ])
  );
}

function renderHide(root) {
  const pads = asList(state.status?.hide?.pads);
  const kids = [
    note(
      "Off looks unplugged to Steam/NMH3. Cable stays. The pad driving Steam cannot hide itself."
    ),
    row("", [
      btn("Re-apply hidden.json", {
        click: () => run("Hide apply", "hide", "apply"),
      }),
    ]),
  ];
  if (!pads.length) {
    kids.push(
      note(
        state.status?.hide?.message ||
          "No hideable pads, or hide-controllers.py is not on this checkout."
      )
    );
  }
  pads.forEach((pad) => {
    const item = document.createElement("div");
    item.className = "item";
    const title = document.createElement("p");
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = pad.hidden ? "hidden" : "visible";
    title.appendChild(chip);
    title.appendChild(document.createTextNode(` ${pad.name || pad.id}`));
    item.appendChild(title);
    item.appendChild(note(padDescription(pad)));
    const hidden = pad.hidden === true;
    const cannotHide = !hidden && pad.can_disable === false;
    item.appendChild(
      row("choice", [
        btn(hidden ? "Show" : "Hide", {
          danger: !hidden,
          disabled: cannotHide,
          click: () =>
            run(hidden ? "Pad connected" : "Pad hidden", "hide", "set", {
              pad_id: pad.id,
              hidden: hidden ? "show" : "hide",
            }),
        }),
      ])
    );
    kids.push(item);
  });
  root.appendChild(card("Hide pads", kids));
}

function renderMore(root) {
  const emu = state.status?.emu || {};
  const emus = emu.emus || {};
  const tips = asList(state.status?.tips);
  const emuKids = [note(emu.apply || "Emu Quick status. Writes stay in QAM / SSH.")];
  ["eden", "azahar", "cemu"].forEach((name) => {
    const rowEmu = emus[name] || {};
    const item = document.createElement("div");
    item.className = "item";
    item.appendChild(
      note(
        `${name} ${rowEmu.running ? "running" : "idle"}${
          rowEmu.title ? ` · ${rowEmu.title}` : ""
        }`
      )
    );
    item.appendChild(
      btn(`Refresh ${name}`, {
        click: () => run(`${name} status`, "emu", "status", { emu: name }),
      })
    );
    emuKids.push(item);
  });
  root.appendChild(card("Emu", emuKids));
  root.appendChild(
    card("Saves", [
      note("Official Syncthing mesh. Does not start GTK or decky-syncthing."),
      row("choice", [
        btn("Ensure mesh", {
          click: () => run("Saves ensure", "saves", "ensure"),
        }),
      ]),
    ])
  );
  const tipBox = document.createElement("div");
  tipBox.className = "item";
  (tips.length ? tips : ["fgpc-api dump has no tips yet."]).forEach((tip, i) => {
    const p = document.createElement("p");
    p.className = "tip";
    p.textContent = `${i + 1}. ${tip}`;
    tipBox.appendChild(p);
  });
  root.appendChild(card("Tips", [tipBox]));
}

function render() {
  const tabs = $("tabs");
  tabs.innerHTML = "";
  TABS.forEach((tab) => {
    tabs.appendChild(
      btn(tab.label, {
        on: state.tab === tab.id,
        click: () => {
          state.tab = tab.id;
          render();
        },
      })
    );
  });
  const panels = $("panels");
  panels.innerHTML = "";
  if (state.tab === "stream") renderStream(panels);
  else if (state.tab === "screen") renderScreen(panels);
  else if (state.tab === "pad") renderPad(panels);
  else if (state.tab === "hide") renderHide(panels);
  else renderMore(panels);
}

$("refresh").addEventListener("click", refresh);
render();
refresh();
setInterval(() => {
  if (!state.busy) refresh();
}, 8000);
