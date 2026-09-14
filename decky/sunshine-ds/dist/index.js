const manifest = { name: "Sunshine DS" };
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
const startDesktopDs = callable("start_desktop_ds");

function Content() {
  const [status, setStatus] = SP_REACT.useState(null);
  const [busy, setBusy] = SP_REACT.useState(false);

  SP_REACT.useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const next = await getStatus();
        if (!cancelled) setStatus(next);
      } catch (err) {
        console.error(err);
      }
    };
    refresh();
    const id = setInterval(refresh, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const start = async () => {
    if (busy) return;
    setBusy(true);
    toaster.toast({
      title: "Dual-Stream Desktop",
      body: "Leaving Game Mode. Moonlight stays on :48100.",
      duration: 4000,
    });
    try {
      const result = await startDesktopDs();
      toaster.toast({
        title: result?.ok ? "Switching" : "Failed",
        body: (result?.message || "").slice(0, 220),
        duration: result?.ok ? 4000 : 7000,
      });
    } catch (err) {
      toaster.toast({
        title: "Failed",
        body: String(err).slice(0, 220),
        duration: 7000,
      });
    } finally {
      setBusy(false);
    }
  };

  return SP_JSX.jsxs(SP_JSX.Fragment, {
    children: [
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "Proven sunshine-ds",
        children: [
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsxs("div", {
              style: { display: "flex", flexDirection: "column", gap: 6 },
              children: [
                SP_JSX.jsx("div", {
                  style: { fontSize: "1.15em", fontWeight: 600 },
                  children: status?.headline ?? "Loading…",
                }),
                SP_JSX.jsx("div", {
                  style: { opacity: 0.75, fontSize: "0.92em" },
                  children: status?.detail ?? "",
                }),
                SP_JSX.jsx("div", {
                  style: { opacity: 0.55, fontSize: "0.85em" },
                  children: status
                    ? `gamescope ${status.gamescope ? "up" : "down"} · plasma ${
                        status.plasma ? "up" : "down"
                      } · :48100 ${status.ds}`
                    : "",
                }),
              ],
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: busy,
              onClick: start,
              children: "Start Dual-Stream Desktop",
            }),
          }),
        ],
      }),
      SP_JSX.jsx(DFL.PanelSection, {
        title: "Moonlight",
        children: SP_JSX.jsx(DFL.PanelSectionRow, {
          children: SP_JSX.jsx("div", {
            style: { opacity: 0.65, fontSize: "0.88em" },
            children:
              "This plugin does not launch games. After Plasma is up, connect Thor/Odin to :48100 and use Desktop, Cemu Dual-Screen, or Azahar Dual-Screen. Return to Game Mode is a Sunshine app (teardown).",
          }),
        }),
      }),
    ],
  });
}

var index = definePlugin(() => ({
  name: "Sunshine DS",
  titleView: SP_JSX.jsx("div", {
    className: DFL.staticClasses.Title,
    children: "Sunshine DS",
  }),
  content: SP_JSX.jsx(Content, {}),
  icon: SP_JSX.jsx("span", { children: "DS" }),
}));

export { index as default };
