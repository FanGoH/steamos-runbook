const manifest = { name: "Second Screen" };
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
const setDualScreen = callable("set_dual_screen");
const showWindow = callable("show_window");
const idleClock = callable("idle_clock");

function asWindows(raw) {
  if (Array.isArray(raw)) return raw;
  return [];
}

function windowLabel(win) {
  const name = win?.name || "(unnamed)";
  const size = `${win?.width || "?"}×${win?.height || "?"}`;
  return `${name} · ${win?.display || "?"} · ${size}`;
}

function Content() {
  const [status, setStatus] = SP_REACT.useState(null);
  const [dualScreen, setDualScreenMode] = SP_REACT.useState("auto");
  const [busy, setBusy] = SP_REACT.useState(false);
  const [error, setError] = SP_REACT.useState("");

  const refresh = SP_REACT.useCallback(async () => {
    try {
      const next = await getStatus();
      setStatus(next);
      setError(next?.ok === false ? next.message || "status failed" : "");
      const ds = next?.dual_screen || next?.dual_screen_live?.mode;
      if (ds === "auto" || ds === "on" || ds === "off") {
        setDualScreenMode(ds);
      }
    } catch (err) {
      setError(String(err));
    }
  }, []);

  SP_REACT.useEffect(() => {
    refresh();
    const id = setInterval(refresh, 4000);
    return () => clearInterval(id);
  }, [refresh]);

  const persistDualScreen = async (nextMode) => {
    setDualScreenMode(nextMode);
    try {
      const result = await setDualScreen(nextMode);
      if (result?.ok === false) {
        toaster.toast({
          title: "Second Screen",
          body: result.message || "toggle failed",
          duration: 5000,
        });
      }
      await refresh();
    } catch (err) {
      toaster.toast({
        title: "Second Screen",
        body: String(err).slice(0, 220),
        duration: 5000,
      });
    }
  };

  const run = async (title, fn) => {
    if (busy) return;
    setBusy(true);
    try {
      const result = await fn();
      const body = (result?.messages || [result?.message || ""])
        .filter(Boolean)
        .join(" ")
        .slice(0, 220);
      toaster.toast({
        title: result?.ok === false ? "Second Screen failed" : title,
        body: body || title,
        duration: result?.ok === false ? 7000 : 4000,
      });
      await refresh();
    } catch (err) {
      toaster.toast({
        title: "Second Screen failed",
        body: String(err).slice(0, 220),
        duration: 7000,
      });
    } finally {
      setBusy(false);
    }
  };

  const windows = asWindows(status?.windows);

  return SP_JSX.jsxs(SP_JSX.Fragment, {
    children: [
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "Emulator dual-screen",
        children: [
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx("div", {
              style: { opacity: 0.75, fontSize: "0.88em" },
              children:
                status?.dual_screen_live?.reason ||
                error ||
                "Auto: Cemu/Azahar GamePad layout only when Moonlight is watching the bottom.",
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsxs("div", {
              style: { display: "flex", gap: 8, flexWrap: "wrap" },
              children: [
                SP_JSX.jsx(DFL.ButtonItem, {
                  layout: "below",
                  onClick: () => persistDualScreen("auto"),
                  children: dualScreen === "auto" ? "Auto DS ✓" : "Auto DS",
                }),
                SP_JSX.jsx(DFL.ButtonItem, {
                  layout: "below",
                  onClick: () => persistDualScreen("on"),
                  children: dualScreen === "on" ? "Dual-screen ✓" : "Dual-screen",
                }),
                SP_JSX.jsx(DFL.ButtonItem, {
                  layout: "below",
                  onClick: () => persistDualScreen("off"),
                  children: dualScreen === "off" ? "HDMI only ✓" : "HDMI only",
                }),
              ],
            }),
          }),
        ],
      }),
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "Gamescope windows",
        children: [
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx("div", {
              style: { opacity: 0.75, fontSize: "0.88em" },
              children: status?.mirror?.running
                ? `Bottom stream is mirroring a window (ffplay ${status.mirror.pid}).`
                : `Bottom is ${status?.pad_display || ":2"} (idle clock unless you pick a window).`,
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: busy,
              onClick: refresh,
              children: "Refresh windows",
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: busy,
              onClick: () => run("Idle clock", () => idleClock()),
              children: "Moonlight Screensaver",
            }),
          }),
          ...(windows.length
            ? windows.flatMap((win) => [
                SP_JSX.jsx(
                  DFL.PanelSectionRow,
                  {
                    children: SP_JSX.jsxs("div", {
                      style: {
                        display: "flex",
                        flexDirection: "column",
                        gap: 6,
                      },
                      children: [
                        SP_JSX.jsx("div", {
                          style: { opacity: 0.9, fontSize: "0.9em" },
                          children: windowLabel(win),
                        }),
                        SP_JSX.jsx(DFL.ButtonItem, {
                          layout: "below",
                          disabled: busy,
                          onClick: () =>
                            run("Second screen", () =>
                              showWindow(win.display, win.id)
                            ),
                          children:
                            win.display === (status?.pad_display || ":2")
                              ? "Maximize on bottom"
                              : "Show on second screen",
                        }),
                      ],
                    }),
                  },
                  `${win.display}-${win.id}`
                ),
              ])
            : [
                SP_JSX.jsx(
                  DFL.PanelSectionRow,
                  {
                    children: SP_JSX.jsx("div", {
                      style: { opacity: 0.75, fontSize: "0.88em" },
                      children: "No session windows yet. Open a game, then Refresh.",
                    }),
                  },
                  "empty"
                ),
              ]),
        ],
      }),
    ],
  });
}

var index = definePlugin(() => ({
  name: "Second Screen",
  titleView: SP_JSX.jsx("div", {
    className: DFL.staticClasses.Title,
    children: "Second Screen",
  }),
  content: SP_JSX.jsx(Content, {}),
  icon: SP_JSX.jsx("span", { children: "2" }),
}));

export { index as default };
