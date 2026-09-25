const manifest = { name: "Switch 2" };
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
const startBridge = callable("start");
const stopBridge = callable("stop");
const gripBridge = callable("grip");
const reconnectBridge = callable("reconnect");

function Content() {
  const [status, setStatus] = SP_REACT.useState(null);
  const [busy, setBusy] = SP_REACT.useState("");
  const [error, setError] = SP_REACT.useState("");

  const refresh = SP_REACT.useCallback(async () => {
    try {
      const next = await getStatus();
      setStatus(next);
      setError(next?.ok === false ? next.message || "status failed" : "");
    } catch (err) {
      setError(String(err));
    }
  }, []);

  SP_REACT.useEffect(() => {
    refresh();
    const id = setInterval(refresh, 4000);
    return () => clearInterval(id);
  }, [refresh]);

  const run = async (title, fn) => {
    if (busy) return;
    setBusy(title);
    try {
      const result = await fn();
      toaster.toast({
        title: result?.ok === false ? "Switch 2 failed" : title,
        body: (result?.message || title).slice(0, 220),
        duration: result?.ok === false ? 7000 : 4000,
      });
      await refresh();
    } catch (err) {
      toaster.toast({
        title: "Switch 2 failed",
        body: String(err).slice(0, 220),
        duration: 7000,
      });
    } finally {
      setBusy("");
    }
  };

  const sw = status?.switch || {};
  const src = status?.source;
  const summary = status?.message || "…";

  return SP_JSX.jsxs(SP_JSX.Fragment, {
    children: [
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "NUXBT → Switch 2",
        children: [
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx("div", {
              style: { opacity: 0.85, fontSize: "0.9em", lineHeight: 1.4 },
              children: error || summary,
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx("div", {
              style: { opacity: 0.7, fontSize: "0.82em", lineHeight: 1.35 },
              children: [
                `Bridge: ${status?.running ? "up" : "down"} · state: ${status?.state || "?"}`,
                SP_JSX.jsx("br", {}),
                `Switch: ${
                  sw.connected ? "connected" : sw.paired ? "paired" : "—"
                } ${sw.address || status?.switch_mac || ""}`,
                SP_JSX.jsx("br", {}),
                src
                  ? `Source: ${src.name}`
                  : "Source: no Sunshine pad (start Moonlight)",
              ],
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: Boolean(busy),
              onClick: () => run("Reconnect", reconnectBridge),
              children: busy === "Reconnect" ? "…" : "Reconnect (MAC + radio prep)",
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: Boolean(busy),
              onClick: () => run("Grip / Order", gripBridge),
              children:
                busy === "Grip / Order"
                  ? "…"
                  : "Grip / Order (dongle prep + advertise)",
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: Boolean(busy),
              onClick: () => run("Start", startBridge),
              children: busy === "Start" ? "…" : "Start bridge",
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: Boolean(busy),
              onClick: () => run("Stop", stopBridge),
              children: busy === "Stop" ? "…" : "Stop bridge",
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: Boolean(busy),
              onClick: refresh,
              children: "Refresh",
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx("div", {
              style: { opacity: 0.6, fontSize: "0.78em", lineHeight: 1.35 },
              children:
                "Grip / Reconnect run USB dongle prep (power-cycle hci1) then hard-restart the bridge. Stay on Change Grip/Order for Grip. Close overlay so inputs reach Switch.",
            }),
          }),
        ],
      }),
    ],
  });
}

var index = definePlugin(() => ({
  name: "Switch 2",
  titleView: SP_JSX.jsx("div", {
    className: DFL.staticClasses.Title,
    children: "Switch 2",
  }),
  content: SP_JSX.jsx(Content, {}),
  icon: SP_JSX.jsx("span", { children: "S2" }),
}));

export { index as default };
