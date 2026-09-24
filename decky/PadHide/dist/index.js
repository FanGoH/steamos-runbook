const manifest = { name: "Pad Hide" };
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
const setHidden = callable("set_hidden");

function asPads(raw) {
  if (Array.isArray(raw)) return raw;
  return [];
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

function Content() {
  const [status, setStatus] = SP_REACT.useState(null);
  const [busyId, setBusyId] = SP_REACT.useState("");
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

  const persist = async (pad, connected) => {
    if (busyId) return;
    if (!connected && pad.can_disable === false) {
      toaster.toast({
        title: "Pad Hide",
        body: pad.reason || "This pad cannot hide itself.",
        duration: 4000,
      });
      return;
    }
    setBusyId(pad.id);
    try {
      const result = await setHidden(pad.id, !connected);
      if (result?.ok === false) {
        toaster.toast({
          title: "Pad Hide",
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
        title: "Pad Hide",
        body: String(err).slice(0, 220),
        duration: 5000,
      });
    } finally {
      setBusyId("");
    }
  };

  const pads = asPads(status?.pads);

  return SP_JSX.jsxs(SP_JSX.Fragment, {
    children: [
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "Controllers",
        children: [
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx("div", {
              style: { opacity: 0.75, fontSize: "0.88em" },
              children:
                error ||
                "Off looks unplugged to Steam/NMH3. Cable and Bluetooth stay. The pad driving QAM cannot turn itself off.",
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
                        Boolean(busyId) ||
                        (pad.hidden !== true && pad.can_disable === false),
                      onChange: (on) => persist(pad, Boolean(on)),
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
                  "empty"
                ),
              ]),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: Boolean(busyId),
              onClick: refresh,
              children: "Refresh pads",
            }),
          }),
        ],
      }),
    ],
  });
}

var index = definePlugin(() => ({
  name: "Pad Hide",
  titleView: SP_JSX.jsx("div", {
    className: DFL.staticClasses.Title,
    children: "Pad Hide",
  }),
  content: SP_JSX.jsx(Content, {}),
  icon: SP_JSX.jsx("span", { children: "Pad" }),
}));

export { index as default };
