const manifest = { name: "FGPC" };
const API_VERSION = 2;
const internalAPIConnection =
  window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
if (!internalAPIConnection) {
  throw new Error(
    "[@decky/api]: Failed to connect to the loader as the loader API was not initialized."
  );
}
let api;
try {
  api = internalAPIConnection.connect(API_VERSION, manifest.name);
} catch {
  api = internalAPIConnection.connect(1, manifest.name);
}
const callable = api.callable;
const toaster = api.toaster;
const definePlugin = (fn) => {
  return (...args) => fn(...args);
};

const getStatus = callable("get_status");
const runAction = callable("run_action");

function asList(raw) {
  return Array.isArray(raw) ? raw : [];
}

function streamLine(status) {
  const kms = status?.stream?.gamemode?.message;
  if (kms) return `Game Mode :48200 · ${kms}`;
  if (status?.stream?.note) return status.stream.note;
  return "Game Mode Moonlight is :48200 (not Decky :47989). Use start-kms when :2 is up.";
}

function padDescription(pad) {
  const bits = [];
  if (pad.kind) bits.push(pad.kind);
  if (pad.usb) bits.push(`usb ${pad.usb}`);
  if (pad.js) bits.push(pad.js);
  if (pad.hidden) bits.push(pad.connected ? "hidden (still enumerated)" : "unplugged from the OS");
  else bits.push("connected");
  if (pad.reason) bits.push(pad.reason);
  return bits.join(" · ");
}

function windowLabel(win) {
  const name = win?.name || "(unnamed)";
  const size = `${win?.width || "?"}×${win?.height || "?"}`;
  return `${name} · ${win?.display || "?"} · ${size}`;
}

function Content() {
  const [status, setStatus] = SP_REACT.useState(null);
  const [busy, setBusy] = SP_REACT.useState("");
  const [error, setError] = SP_REACT.useState("");
  const [dual, setDual] = SP_REACT.useState("auto");
  const [padMode, setPadMode] = SP_REACT.useState("shared");

  const refresh = SP_REACT.useCallback(async () => {
    try {
      const next = await getStatus();
      setStatus(next);
      setError(next?.ok === false ? next.message || "status failed" : "");
      const ds = next?.screen?.dual_screen || next?.screen?.dual_screen_live?.mode;
      if (ds === "auto" || ds === "on" || ds === "off") setDual(ds);
      const mode = next?.pad?.mux?.mode;
      if (mode === "shared" || mode === "multi") setPadMode(mode);
    } catch (err) {
      setError(String(err));
    }
  }, []);

  SP_REACT.useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [refresh]);

  const run = async (title, group, action, extra) => {
    if (busy) return;
    setBusy(`${group}:${action}`);
    try {
      const e = extra || {};
      const result = await runAction(
        group,
        action,
        e.pad_id || e.id || "",
        e.mode || "",
        e.emu || "",
        e.display || "",
        e.target || "",
        e.hidden ?? ""
      );
      const body = (result?.messages || [result?.message || ""])
        .filter(Boolean)
        .join(" ")
        .slice(0, 220);
      toaster.toast({
        title: result?.ok === false ? "FGPC failed" : title,
        body: body || title,
        duration: result?.ok === false ? 7000 : 4000,
      });
      await refresh();
    } catch (err) {
      toaster.toast({
        title: "FGPC failed",
        body: String(err).slice(0, 220),
        duration: 7000,
      });
    } finally {
      setBusy("");
    }
  };

  const persistHide = async (pad, connected) => {
    if (busy) return;
    if (!connected && pad.can_disable === false) {
      toaster.toast({
        title: "FGPC",
        body: pad.reason || "This pad cannot hide itself.",
        duration: 4000,
      });
      return;
    }
    setBusy(pad.id);
    try {
      const result = await runAction(
        "hide",
        "set",
        pad.id,
        "",
        "",
        "",
        "",
        connected ? "show" : "hide"
      );
      if (result?.ok === false) {
        toaster.toast({
          title: "FGPC",
          body: result.message || "toggle failed",
          duration: 5000,
        });
      } else {
        toaster.toast({
          title: connected ? "Pad connected" : "Pad hidden",
          body: connected
            ? `${pad.name || pad.id} is visible to Steam/games again.`
            : `${pad.name || pad.id} looks unplugged. Cable stays.`,
          duration: 4000,
        });
      }
      await refresh();
    } catch (err) {
      toaster.toast({
        title: "FGPC",
        body: String(err).slice(0, 220),
        duration: 5000,
      });
    } finally {
      setBusy("");
    }
  };

  const windows = asList(status?.screen?.windows);
  const pads = asList(status?.hide?.pads);
  const tips = asList(status?.tips);
  const mux = status?.pad?.mux || {};

  return SP_JSX.jsxs(SP_JSX.Fragment, {
    children: [
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "Stream :48200",
        children: [
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx("div", {
              style: { opacity: 0.75, fontSize: "0.88em" },
              children: error || streamLine(status),
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: Boolean(busy),
              onClick: () => run("Start kms", "stream", "start-kms"),
              children: busy === "stream:start-kms" ? "Starting…" : "Start kms",
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: Boolean(busy),
              onClick: () => run("Paint clock", "stream", "paint"),
              children: "Paint clock",
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: Boolean(busy),
              onClick: () => run("Stop kms", "stream", "stop"),
              children: "Stop kms",
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: Boolean(busy),
              onClick: () => run("Close Cemu", "stream", "close-cemu"),
              children: "Close Cemu leftover",
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: Boolean(busy),
              onClick: () => run("Close Azahar", "stream", "close-azahar"),
              children: "Close Azahar leftover",
            }),
          }),
        ],
      }),
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "Screen",
        children: [
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx("div", {
              style: { opacity: 0.75, fontSize: "0.88em" },
              children:
                status?.screen?.dual_screen_live?.reason ||
                "Auto: GamePad layout only when Moonlight watches the bottom.",
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsxs("div", {
              style: { display: "flex", gap: 8, flexWrap: "wrap" },
              children: [
                SP_JSX.jsx(DFL.ButtonItem, {
                  layout: "below",
                  onClick: () => {
                    setDual("auto");
                    run("Auto DS", "screen", "dual", { mode: "auto" });
                  },
                  children: dual === "auto" ? "Auto DS ✓" : "Auto DS",
                }),
                SP_JSX.jsx(DFL.ButtonItem, {
                  layout: "below",
                  onClick: () => {
                    setDual("on");
                    run("Dual-screen", "screen", "dual", { mode: "on" });
                  },
                  children: dual === "on" ? "Dual-screen ✓" : "Dual-screen",
                }),
                SP_JSX.jsx(DFL.ButtonItem, {
                  layout: "below",
                  onClick: () => {
                    setDual("off");
                    run("HDMI only", "screen", "dual", { mode: "off" });
                  },
                  children: dual === "off" ? "HDMI only ✓" : "HDMI only",
                }),
              ],
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: Boolean(busy),
              onClick: () => run("Idle clock", "screen", "clock"),
              children: "Moonlight Screensaver",
            }),
          }),
          ...(windows.length
            ? windows.map((win) =>
                SP_JSX.jsx(
                  DFL.PanelSectionRow,
                  {
                    children: SP_JSX.jsxs("div", {
                      style: { display: "flex", flexDirection: "column", gap: 6 },
                      children: [
                        SP_JSX.jsx("div", {
                          style: { opacity: 0.9, fontSize: "0.9em" },
                          children: windowLabel(win),
                        }),
                        SP_JSX.jsx(DFL.ButtonItem, {
                          layout: "below",
                          disabled: Boolean(busy),
                          onClick: () =>
                            run("Second screen", "screen", "show", {
                              id: win.id,
                              display: win.display,
                            }),
                          children:
                            win.display === (status?.screen?.pad_display || ":2")
                              ? "Maximize on bottom"
                              : "Show on second screen",
                        }),
                      ],
                    }),
                  },
                  `${win.display}-${win.id}`
                )
              )
            : [
                SP_JSX.jsx(
                  DFL.PanelSectionRow,
                  {
                    children: SP_JSX.jsx("div", {
                      style: { opacity: 0.75, fontSize: "0.88em" },
                      children: "No session windows yet. Open a game, then Refresh.",
                    }),
                  },
                  "empty-windows"
                ),
              ]),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: Boolean(busy),
              onClick: refresh,
              children: "Refresh",
            }),
          }),
        ],
      }),
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "Pad",
        children: [
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx("div", {
              style: { opacity: 0.75, fontSize: "0.88em" },
              children: mux.running
                ? `EmuPads mux ${mux.mode || padMode} · bind P1/P2`
                : "Mux down. Apply still starts it via bind-gamepad.py.",
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsxs("div", {
              style: { display: "flex", gap: 8, flexWrap: "wrap" },
              children: [
                SP_JSX.jsx(DFL.ButtonItem, {
                  layout: "below",
                  onClick: () => {
                    setPadMode("shared");
                    run("Shared P1", "pad", "mode", { mode: "shared" });
                  },
                  children: padMode === "shared" ? "Shared ✓" : "Shared",
                }),
                SP_JSX.jsx(DFL.ButtonItem, {
                  layout: "below",
                  onClick: () => {
                    setPadMode("multi");
                    run("Multi P1+P2", "pad", "mode", { mode: "multi" });
                  },
                  children: padMode === "multi" ? "Multi ✓" : "Multi",
                }),
              ],
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: Boolean(busy),
              onClick: () =>
                run("Apply binds", "pad", "apply", { emu: "all", mode: padMode }),
              children: busy === "pad:apply" ? "Applying…" : "Apply binds",
            }),
          }),
        ],
      }),
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "Hide",
        children: [
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx("div", {
              style: { opacity: 0.75, fontSize: "0.88em" },
              children:
                "Off looks unplugged to Steam/NMH3. Cable stays. The pad driving QAM cannot turn itself off.",
            }),
          }),
          ...(pads.length
            ? pads.map((pad) =>
                SP_JSX.jsx(
                  DFL.PanelSectionRow,
                  {
                    children: SP_JSX.jsx(DFL.ToggleField, {
                      label: pad.name || pad.id,
                      description: padDescription(pad),
                      checked: pad.hidden !== true,
                      disabled:
                        Boolean(busy) ||
                        (pad.hidden !== true && pad.can_disable === false),
                      onChange: (on) => persistHide(pad, Boolean(on)),
                    }),
                  },
                  pad.id
                )
              )
            : [
                SP_JSX.jsx(
                  DFL.PanelSectionRow,
                  {
                    children: SP_JSX.jsx("div", {
                      style: { opacity: 0.75, fontSize: "0.88em" },
                      children: "No hideable pads. Plug in a USB/Bluetooth controller.",
                    }),
                  },
                  "empty-pads"
                ),
              ]),
        ],
      }),
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "Tips",
        children: [
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx("div", {
              style: {
                opacity: 0.8,
                fontSize: "0.82em",
                whiteSpace: "pre-wrap",
              },
              children: (tips.length ? tips : ["fgpc-api dump has no tips yet."])
                .map((tip, i) => `${i + 1}. ${tip}`)
                .join("\n"),
            }),
          }),
        ],
      }),
    ],
  });
}

var index = definePlugin(() => ({
  name: "FGPC",
  titleView: SP_JSX.jsx("div", {
    className: DFL.staticClasses.Title,
    children: "FGPC",
  }),
  content: SP_JSX.jsx(Content, {}),
  icon: SP_JSX.jsx("span", { children: "fg" }),
}));

export { index as default };
