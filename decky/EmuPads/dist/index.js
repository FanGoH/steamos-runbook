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
const setMuxMode = callable("set_mode");
const setDualScreen = callable("set_dual_screen");

function asPads(raw) {
  if (Array.isArray(raw)) return raw;
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return [];
}

function isSteamPad(pad) {
  return pad?.steam === true || pad?.steam === "true";
}

function padKind(pad) {
  if (pad?.sunshine === "true" || pad?.sunshine === true || /sunshine/i.test(pad?.name || "")) return "Sunshine";
  if (isSteamPad(pad)) return "Steam virtual";
  const vid = (pad?.vendor || "").toLowerCase();
  if (vid === "045e") return "Xbox";
  if (vid === "057e") return "Switch";
  if (vid === "054c") return "PlayStation";
  return "Pad";
}

function playerLine(players, slot) {
  const hit = (players || []).find((p) => p.slot === slot);
  if (!hit) return "—";
  const name = hit.name || hit.guid || hit.uuid || "bound";
  return hit.type ? `${name} (${hit.type})` : name;
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
  const [mode, setMode] = SP_REACT.useState("shared");
  const [cemuP1, setCemuP1] = SP_REACT.useState("gamepad");
  const [dualScreen, setDualScreenMode] = SP_REACT.useState("auto");
  const [busy, setBusy] = SP_REACT.useState(false);
  const [error, setError] = SP_REACT.useState("");
  const modeTouched = SP_REACT.useRef(false);

  const refresh = SP_REACT.useCallback(async (opts) => {
    try {
      const next = await getStatus();
      setStatus(next);
      setError(next?.ok === false ? next.message || "status failed" : "");
      const rawPads = asPads(next?.pads);
      const realPads = rawPads.filter((p) => !isSteamPad(p));
      const pads = realPads.length ? realPads : rawPads;
      setOrder((prev) => mergeOrder(prev, pads));
      if (
        (!modeTouched.current || opts?.syncMode) &&
        (next?.mux?.mode === "multi" || next?.mux?.mode === "shared")
      ) {
        setMode(next.mux.mode);
      }
      if (next?.mux?.cemu_p1 === "pro" || next?.mux?.cemu_p1 === "gamepad") {
        setCemuP1(next.mux.cemu_p1);
      } else if (next?.cemu_p1 === "pro" || next?.cemu_p1 === "gamepad") {
        setCemuP1(next.cemu_p1);
      }
      const ds = next?.mux?.dual_screen || next?.dual_screen;
      if (ds === "auto" || ds === "on" || ds === "off") {
        setDualScreenMode(ds);
      }
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
  for (const pad of asPads(status?.pads)) padsByJs[pad.js] = pad;
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

  const persistDualScreen = async (nextMode) => {
    setDualScreenMode(nextMode);
    try {
      const result = await setDualScreen(nextMode);
      if (result?.ok === false) {
        return;
      }
      await refresh();
    } catch (_err) {
      // set_dual_screen is missing until Decky reloads main.py.
    }
  };

  const persistMode = async (nextMode) => {
    modeTouched.current = true;
    setMode(nextMode);
    try {
      const result = await setMuxMode(nextMode);
      if (result?.ok === false) {
        return;
      }
      await refresh({ syncMode: true });
    } catch (_err) {
      // set_mode is missing until Decky reloads main.py; the check still sticks.
    }
  };

  const apply = async (emu, restart) => {
    if (busy) return;
    const muxUp = Boolean(status?.mux?.running);
    if (!selected.length && !muxUp) {
      toaster.toast({
        title: "Emu Pads",
        body:
          status?.pad_hint ||
          "No host pad yet. Reconnect Moonlight Odin/Thor, then Refresh pads.",
        duration: 5000,
      });
      return;
    }
    setBusy(true);
    const allOn =
      orderedPads.length > 0 && orderedPads.every((p) => included[p.js] !== false);
    const pads = allOn ? "" : selected.map((p) => p.js).join(",");
    try {
      const result = await applyBinds(emu, pads, mode, cemuP1, Boolean(restart));
      const body = (result?.messages || [result?.message || ""])
        .filter(Boolean)
        .join(" ")
        .slice(0, 220);
      toaster.toast({
        title:
          result?.ok === false
            ? "Bind failed"
            : restart
            ? "Applied and restarted"
            : "Applied",
        body: body || `${emu}: ${mode} ${selected.map((p) => p.name).join(" → ")}`,
        duration: result?.ok === false ? 7000 : 5000,
      });
      await refresh({ syncMode: true });
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
                ? SP_JSX.jsx("div", {
                    children:
                      "Running — Apply keeps routing live; Apply and restart reloads binds.",
                  })
                : null,
              extra
                ? SP_JSX.jsx("div", { style: { opacity: 0.7, fontSize: "0.85em" }, children: extra })
                : null,
            ],
          }),
        }),
        key === "cemu"
          ? SP_JSX.jsx(DFL.PanelSectionRow, {
              children: SP_JSX.jsxs("div", {
                style: { display: "flex", gap: 8, flexWrap: "wrap" },
                children: [
                  SP_JSX.jsx(DFL.ButtonItem, {
                    layout: "below",
                    onClick: () => setCemuP1("gamepad"),
                    children: cemuP1 === "gamepad" ? "GamePad ✓" : "GamePad",
                  }),
                  SP_JSX.jsx(DFL.ButtonItem, {
                    layout: "below",
                    onClick: () => setCemuP1("pro"),
                    children: cemuP1 === "pro" ? "Pro Controller ✓" : "Pro Controller",
                  }),
                ],
              }),
            })
          : null,
        SP_JSX.jsx(DFL.PanelSectionRow, {
          children: SP_JSX.jsx(DFL.ButtonItem, {
            layout: "below",
            disabled: busy,
            onClick: () => apply(key),
            children: `Apply to ${title}`,
          }),
        }),
        SP_JSX.jsx(DFL.PanelSectionRow, {
          children: SP_JSX.jsx(DFL.ButtonItem, {
            layout: "below",
            disabled: busy,
            onClick: () => apply(key, true),
            children: `Apply and restart ${title}`,
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
                  (orderedPads.length === 0
                    ? status?.pad_hint ||
                      "No Moonlight Odin/Thor pad yet. Reconnect, then Refresh. Mux can still bind EmuPads P1."
                    : mode === "multi"
                    ? `Multi: first selected is P1, second is P2 (${selected.length} selected).`
                    : `Shared P1: last pad used wins. Every host pad is a source (${selected.length} selected).`),
              ],
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsxs("div", {
              style: { opacity: 0.75, fontSize: "0.88em" },
              children: [
                `Mux ${status?.mux?.running ? "up" : "down"} · ${status?.mux?.mode || mode}${
                  status?.mux?.muted ? " · muted" : ""
                }`,
              ],
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsxs("div", {
              style: { display: "flex", gap: 8, flexWrap: "wrap" },
              children: [
                SP_JSX.jsx(DFL.ButtonItem, {
                  layout: "below",
                  onClick: () => persistMode("shared"),
                  children: mode === "shared" ? "Shared P1 ✓" : "Shared P1",
                }),
                SP_JSX.jsx(DFL.ButtonItem, {
                  layout: "below",
                  onClick: () => persistMode("multi"),
                  children: mode === "multi" ? "Multiplayer ✓" : "Multiplayer",
                }),
              ],
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsxs("div", {
              style: { opacity: 0.75, fontSize: "0.88em" },
              children: [
                status?.dual_screen_live?.reason ||
                  "Auto dual-screen: Cemu/Azahar GamePad layout only when Moonlight is watching the bottom.",
              ],
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
          ...(orderedPads.length
            ? orderedPads.flatMap((pad, index) => [
                SP_JSX.jsx(
                  DFL.PanelSectionRow,
                  {
                    children: SP_JSX.jsx(DFL.ToggleField, {
                      label: pad.name || pad.js,
                      description: `${pad.js} · ${padKind(pad)} · ${
                        included[pad.js] === false ? "skipped" : "included"
                      }`,
                      checked: included[pad.js] !== false,
                      onChange: (on) =>
                        setIncluded((prev) => ({ ...prev, [pad.js]: Boolean(on) })),
                    }),
                  },
                  pad.js
                ),
                SP_JSX.jsx(
                  DFL.PanelSectionRow,
                  {
                    children: SP_JSX.jsxs("div", {
                      style: { display: "flex", gap: 8, flexWrap: "wrap" },
                      children: [
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
                  },
                  `${pad.js}-order`
                ),
              ])
            : []),
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
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: busy,
              onClick: () => apply("all", true),
              children: "Apply and restart emulation",
            }),
          }),
        ],
      }),
      emuBlock(
        "cemu",
        "Cemu",
        [status?.emus?.cemu?.p1, status?.emus?.cemu?.p2].filter(Boolean).join(" ")
      ),
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
