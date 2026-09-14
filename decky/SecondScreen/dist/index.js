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

function asClients(status) {
  const list = status?.clients || status?.dual_screen_live?.clients;
  return Array.isArray(list) ? list : [];
}

function clientsSignature(clients) {
  return clients
    .map(
      (client) =>
        `${client?.device || client?.name || ""}|${client?.watch || ""}|${client?.config || ""}`
    )
    .sort()
    .join(";");
}

function clientNames(clients) {
  const names = clients
    .map((client) => client?.name || client?.device || "")
    .filter(Boolean);
  return names.length ? names.join(" · ") : "";
}

function modeToast(status, clients) {
  const live = status?.dual_screen_live || {};
  const names = clientNames(clients) || "Moonlight";
  const reason = live.reason || "";
  if (!clients.length) {
    return {
      title: "HDMI only",
      body: reason ? `No Moonlight clients — ${reason}` : "No Moonlight clients",
    };
  }
  if (live.wanted) {
    return {
      title: "Dual-screen",
      body: reason ? `${names} · ${reason}` : names,
    };
  }
  return {
    title: "HDMI only",
    body: reason ? `${names} · ${reason}` : `${names} · top screen only`,
  };
}

function windowLabel(win) {
  const name = win?.name || "(unnamed)";
  const size = `${win?.width || "?"}×${win?.height || "?"}`;
  return `${name} · ${win?.display || "?"} · ${size}`;
}

function clientField(client, key) {
  const name = client?.name || client?.device || "Moonlight";
  const detail = client?.config
    ? client.device && client.device !== name
      ? `${client.config} · ${client.device}`
      : client.config
    : client?.device || "connected";
  return SP_JSX.jsx(
    DFL.PanelSectionRow,
    {
      children: SP_JSX.jsx(DFL.Field, {
        label: name,
        children: detail,
      }),
    },
    key
  );
}

function PluginTitle() {
  const [names, setNames] = SP_REACT.useState("");
  SP_REACT.useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const next = await getStatus();
        if (!cancelled) setNames(clientNames(asClients(next)));
      } catch (_err) {
        if (!cancelled) setNames("");
      }
    };
    tick();
    const id = setInterval(tick, 4000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);
  return SP_JSX.jsx("div", {
    className: DFL.staticClasses.Title,
    children: names ? `Second Screen · ${names}` : "Second Screen",
  });
}

function Content() {
  const [status, setStatus] = SP_REACT.useState(null);
  const [dualScreen, setDualScreenMode] = SP_REACT.useState("auto");
  const [busy, setBusy] = SP_REACT.useState(false);
  const [error, setError] = SP_REACT.useState("");
  const lastModeSig = SP_REACT.useRef(null);

  const refresh = SP_REACT.useCallback(async () => {
    try {
      const next = await getStatus();
      setStatus(next);
      setError(next?.ok === false ? next.message || "status failed" : "");
      const ds = next?.dual_screen || next?.dual_screen_live?.mode;
      if (ds === "auto" || ds === "on" || ds === "off") {
        setDualScreenMode(ds);
      }
      const nextClients = asClients(next);
      const sig = `${next?.dual_screen_live?.wanted ? "1" : "0"}|${clientsSignature(nextClients)}`;
      if (lastModeSig.current === null) {
        lastModeSig.current = sig;
      } else if (lastModeSig.current !== sig) {
        lastModeSig.current = sig;
        const toast = modeToast(next, nextClients);
        toaster.toast({
          title: toast.title,
          body: toast.body.slice(0, 220),
          duration: 4000,
        });
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
  const clients = asClients(status);

  return SP_JSX.jsxs(SP_JSX.Fragment, {
    children: [
      SP_JSX.jsxs(DFL.PanelSection, {
        title: clients.length
          ? `Moonlight clients (${clients.length})`
          : "Moonlight clients",
        children: [
          ...(clients.length
            ? clients.map((client, idx) =>
                clientField(
                  client,
                  `${client?.device || client?.name || "client"}-${idx}`
                )
              )
            : [
                SP_JSX.jsx(
                  DFL.PanelSectionRow,
                  {
                    children: SP_JSX.jsx(DFL.Field, {
                      label: "None",
                      children: "No Moonlight clients on :48200.",
                    }),
                  },
                  "no-clients"
                ),
              ]),
        ],
      }),
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "Emulator dual-screen",
        children: [
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.Field, {
              label: status?.dual_screen_live?.wanted ? "Dual-screen" : "HDMI only",
              children:
                status?.dual_screen_live?.reason ||
                error ||
                "Auto: Cemu/Azahar GamePad layout only when a client is watching the bottom.",
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx("div", {
              style: { opacity: 0.7, fontSize: "0.82em" },
              children:
                "Tender Cemu/Azahar Play reads this Auto signal at launch (rom-launcher). Steam LaunchOptions stay the RetroDECK line.",
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
  titleView: SP_JSX.jsx(PluginTitle, {}),
  content: SP_JSX.jsx(Content, {}),
  icon: SP_JSX.jsx("span", { children: "2" }),
}));

export { index as default };
