const manifest = { name: "Emu Pads" };
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
const applyBinds = callable("apply");

function padKind(pad) {
  if (pad?.sunshine === "true" || /sunshine/i.test(pad?.name || "")) return "Sunshine";
  if (pad?.steam === "true") return "Steam virtual";
  const vid = (pad?.vendor || "").toLowerCase();
  if (vid === "045e") return "Xbox";
  if (vid === "057e") return "Switch";
  if (vid === "054c") return "PlayStation";
  return "Pad";
}

function playerLine(players, slot) {
  const hit = (players || []).find((p) => p.slot === slot);
  if (!hit) return "—";
  return hit.name || hit.guid || hit.uuid || "bound";
}

function mergeOrder(prev, pads) {
  const ids = pads.map((p) => p.js);
  const keep = (prev || []).filter((id) => ids.includes(id));
  for (const id of ids) {
    if (!keep.includes(id)) keep.push(id);
  }
  return keep;
}

function Content() {
  const [status, setStatus] = SP_REACT.useState(null);
  const [order, setOrder] = SP_REACT.useState([]);
  const [included, setIncluded] = SP_REACT.useState({});
  const [busy, setBusy] = SP_REACT.useState(false);
  const [error, setError] = SP_REACT.useState("");

  const refresh = SP_REACT.useCallback(async () => {
    try {
      const next = await getStatus();
      setStatus(next);
      setError(next?.ok === false ? next.message || "status failed" : "");
      const pads = next?.pads || [];
      setOrder((prev) => mergeOrder(prev, pads));
      setIncluded((prev) => {
        const out = { ...prev };
        for (const pad of pads) {
          if (out[pad.js] === undefined) out[pad.js] = true;
        }
        return out;
      });
    } catch (err) {
      setError(String(err));
    }
  }, []);

  SP_REACT.useEffect(() => {
    refresh();
    const id = setInterval(refresh, 4000);
    return () => clearInterval(id);
  }, [refresh]);

  const padsByJs = {};
  for (const pad of status?.pads || []) padsByJs[pad.js] = pad;
  const orderedPads = order.map((js) => padsByJs[js]).filter(Boolean);
  const selected = orderedPads.filter((p) => included[p.js] !== false);

  const move = (js, dir) => {
    setOrder((prev) => {
      const next = prev.filter((id) => padsByJs[id]);
      const i = next.indexOf(js);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= next.length) return next;
      const copy = next.slice();
      const tmp = copy[i];
      copy[i] = copy[j];
      copy[j] = tmp;
      return copy;
    });
  };

  const apply = async (emu) => {
    if (busy) return;
    if (!selected.length) {
      toaster.toast({
        title: "Emu Pads",
        body: "Turn on at least one pad, then Apply.",
        duration: 4000,
      });
      return;
    }
    setBusy(true);
    const pads = selected.map((p) => p.js).join(",");
    try {
      const result = await applyBinds(emu, pads);
      const body = (result?.messages || [result?.message || ""])
        .filter(Boolean)
        .join(" ")
        .slice(0, 220);
      toaster.toast({
        title: result?.ok === false ? "Bind failed" : "Applied",
        body: body || `${emu}: ${selected.map((p) => p.name).join(" → ")}`,
        duration: result?.ok === false ? 7000 : 5000,
      });
      await refresh();
    } catch (err) {
      toaster.toast({
        title: "Bind failed",
        body: String(err).slice(0, 220),
        duration: 7000,
      });
    } finally {
      setBusy(false);
    }
  };

  const emuBlock = (key, title, extra) => {
    const emu = status?.emus?.[key] || {};
    const players = emu.players || [];
    return SP_JSX.jsxs(DFL.PanelSection, {
      title,
      children: [
        SP_JSX.jsx(DFL.PanelSectionRow, {
          children: SP_JSX.jsxs("div", {
            style: { display: "flex", flexDirection: "column", gap: 4, opacity: 0.85, fontSize: "0.9em" },
            children: [
              SP_JSX.jsx("div", { children: `Player 1: ${playerLine(players, 0)}` }),
              SP_JSX.jsx("div", { children: `Player 2: ${playerLine(players, 1)}` }),
              emu.running
                ? SP_JSX.jsx("div", { children: "Running — restart after apply." })
                : null,
              extra
                ? SP_JSX.jsx("div", { style: { opacity: 0.7, fontSize: "0.85em" }, children: extra })
                : null,
            ],
          }),
        }),
        SP_JSX.jsx(DFL.PanelSectionRow, {
          children: SP_JSX.jsx(DFL.ButtonItem, {
            layout: "below",
            disabled: busy,
            onClick: () => apply(key),
            children: `Apply to ${title}`,
          }),
        }),
      ],
    });
  };

  return SP_JSX.jsxs(SP_JSX.Fragment, {
    children: [
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "Controllers",
        children: [
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsxs("div", {
              style: { opacity: 0.75, fontSize: "0.88em" },
              children: [
                error ||
                  `Order is player 1, then player 2. Sunshine pads keep the client name (${selected.length} selected).`,
              ],
            }),
          }),
          ...orderedPads.map((pad, index) =>
            SP_JSX.jsx(
              DFL.PanelSectionRow,
              {
                children: SP_JSX.jsxs("div", {
                  style: { display: "flex", flexDirection: "column", gap: 6, width: "100%" },
                  children: [
                    SP_JSX.jsx("div", {
                      style: { fontWeight: 600, fontSize: "1.05em" },
                      children: pad.name || pad.js,
                    }),
                    SP_JSX.jsx("div", {
                      style: { opacity: 0.65, fontSize: "0.85em" },
                      children: `${pad.js} · ${padKind(pad)} · ${pad.vendor}:${pad.product}`,
                    }),
                    SP_JSX.jsxs("div", {
                      style: { display: "flex", gap: 8, flexWrap: "wrap" },
                      children: [
                        SP_JSX.jsx(DFL.ButtonItem, {
                          layout: "below",
                          onClick: () =>
                            setIncluded((prev) => ({ ...prev, [pad.js]: prev[pad.js] === false })),
                          children: included[pad.js] === false ? "Skipped" : "Using",
                        }),
                        SP_JSX.jsx(DFL.ButtonItem, {
                          layout: "below",
                          disabled: index === 0,
                          onClick: () => move(pad.js, -1),
                          children: "Up",
                        }),
                        SP_JSX.jsx(DFL.ButtonItem, {
                          layout: "below",
                          disabled: index === orderedPads.length - 1,
                          onClick: () => move(pad.js, 1),
                          children: "Down",
                        }),
                      ],
                    }),
                  ],
                }),
              },
              pad.js
            )
          ),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: busy,
              onClick: refresh,
              children: "Refresh pads",
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: busy,
              onClick: () => apply("all"),
              children: "Apply to Cemu + Azahar + Eden",
            }),
          }),
        ],
      }),
      emuBlock("cemu", "Cemu", status?.emus?.cemu?.p2),
      emuBlock("azahar", "Azahar", status?.emus?.azahar?.p2),
      emuBlock("eden", "Eden", status?.emus?.eden?.p2),
    ],
  });
}

var index = definePlugin(() => ({
  name: "Emu Pads",
  titleView: SP_JSX.jsx("div", {
    className: DFL.staticClasses.Title,
    children: "Emu Pads",
  }),
  content: SP_JSX.jsx(Content, {}),
  icon: SP_JSX.jsx("span", { children: "P1" }),
}));

export { index as default };
