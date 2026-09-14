const manifest = { name: "Emu Quick" };
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
const setSetting = callable("set_setting");
const resetSettings = callable("reset_settings");

const EMUS = [
  { key: "eden", title: "Eden" },
  { key: "azahar", title: "Azahar" },
  { key: "cemu", title: "Cemu" },
];

function nextOption(setting, dir) {
  const options = setting?.options || [];
  if (!options.length) {
    if (setting?.kind === "bool") {
      return setting.value === "true" ? "false" : "true";
    }
    return setting?.value;
  }
  const idx = Math.max(
    0,
    options.findIndex((opt) => opt.value === setting.value)
  );
  const next = (idx + dir + options.length) % options.length;
  return options[next].value;
}

function Content() {
  const [status, setStatus] = SP_REACT.useState(null);
  const [emu, setEmu] = SP_REACT.useState("eden");
  const [scope, setScope] = SP_REACT.useState("global");
  const [titleId, setTitleId] = SP_REACT.useState("");
  const [busy, setBusy] = SP_REACT.useState(false);
  const [error, setError] = SP_REACT.useState("");
  const emuTouched = SP_REACT.useRef(false);
  const titleTouched = SP_REACT.useRef(false);

  const refresh = SP_REACT.useCallback(
    async (opts) => {
      const nextEmu = opts?.emu || emu;
      const nextTitle = opts?.title !== undefined ? opts.title : titleId;
      try {
        const payload = await getStatus(nextEmu, nextTitle);
        setStatus(payload);
        setError(payload?.ok === false ? payload.message || "status failed" : "");
        if (!emuTouched.current && payload?.active) {
          setEmu(payload.active);
        }
        const block = payload?.emus?.[opts?.emu || payload?.active || nextEmu];
        if (!titleTouched.current && block?.title_id) {
          setTitleId(block.title_id);
          if (block.scope_default) setScope(block.scope_default);
        }
      } catch (err) {
        setError(String(err));
      }
    },
    [emu, titleId]
  );

  SP_REACT.useEffect(() => {
    refresh();
    const id = setInterval(() => refresh(), 5000);
    return () => clearInterval(id);
  }, [refresh]);

  const block = status?.emus?.[emu] || {};
  const games = block.games || [];
  const settings = block.settings || [];
  const canPerGame = block.per_game !== false && emu !== "cemu";
  const effectiveTitle = titleId || block.title_id || "";
  const gameName =
    (games.find((g) => g.id === effectiveTitle) || {}).name ||
    block.title ||
    effectiveTitle ||
    "No game selected";

  const toastResult = (title, result) => {
    const body = (result?.messages || [result?.message || ""])
      .filter(Boolean)
      .join(" ")
      .slice(0, 220);
    toaster.toast({
      title: result?.ok === false ? "Save failed" : title,
      body: body || "Restart the game to apply.",
      duration: result?.ok === false ? 7000 : 4000,
    });
  };

  const pickEmu = (key) => {
    emuTouched.current = true;
    titleTouched.current = false;
    setEmu(key);
    setTitleId("");
    setScope(key === "cemu" ? "global" : "global");
    refresh({ emu: key, title: "" });
  };

  const cycleGame = (dir) => {
    if (!games.length) return;
    titleTouched.current = true;
    const ids = games.map((g) => g.id);
    const idx = Math.max(0, ids.indexOf(effectiveTitle));
    const next = ids[(idx + dir + ids.length) % ids.length];
    setTitleId(next);
    setScope("game");
    refresh({ emu, title: next });
  };

  const apply = async (key, value) => {
    if (busy) return;
    if (canPerGame && scope === "game" && !effectiveTitle) {
      toaster.toast({
        title: "Pick a game",
        body: "Select a title, or start one, before saving per-game settings.",
        duration: 5000,
      });
      return;
    }
    setBusy(true);
    try {
      const result = await setSetting(
        emu,
        canPerGame ? scope : "global",
        effectiveTitle,
        key,
        String(value)
      );
      toastResult("Saved", result);
      await refresh({ emu, title: effectiveTitle });
    } catch (err) {
      toaster.toast({
        title: "Save failed",
        body: String(err).slice(0, 220),
        duration: 7000,
      });
    } finally {
      setBusy(false);
    }
  };

  const reset = async (nextScope) => {
    if (busy) return;
    if (nextScope === "game" && !effectiveTitle) return;
    setBusy(true);
    try {
      const result = await resetSettings(emu, nextScope, effectiveTitle);
      toastResult(nextScope === "game" ? "Game reset" : "Defaults restored", result);
      await refresh({ emu, title: effectiveTitle });
    } catch (err) {
      toaster.toast({
        title: "Reset failed",
        body: String(err).slice(0, 220),
        duration: 7000,
      });
    } finally {
      setBusy(false);
    }
  };

  const settingRow = (setting) => {
    const badge = canPerGame && setting.use_global === false ? " · this game" : "";
    if (setting.kind === "bool" && DFL.ToggleField) {
      return SP_JSX.jsx(
        DFL.PanelSectionRow,
        {
          children: SP_JSX.jsx(DFL.ToggleField, {
            label: setting.label + badge,
            checked: setting.value === "true",
            disabled: busy,
            onChange: (on) => apply(setting.key, on ? "true" : "false"),
          }),
        },
        setting.key
      );
    }
    return SP_JSX.jsx(
      DFL.PanelSectionRow,
      {
        children: SP_JSX.jsxs("div", {
          style: { display: "flex", flexDirection: "column", gap: 6, width: "100%" },
          children: [
            SP_JSX.jsx("div", {
              style: { fontWeight: 600 },
              children: `${setting.label}: ${setting.display || setting.value}${badge}`,
            }),
            SP_JSX.jsxs("div", {
              style: { display: "flex", gap: 8, flexWrap: "wrap" },
              children: [
                SP_JSX.jsx(DFL.ButtonItem, {
                  layout: "below",
                  disabled: busy,
                  onClick: () => apply(setting.key, nextOption(setting, -1)),
                  children: "−",
                }),
                SP_JSX.jsx(DFL.ButtonItem, {
                  layout: "below",
                  disabled: busy,
                  onClick: () => apply(setting.key, nextOption(setting, 1)),
                  children: "+",
                }),
              ],
            }),
          ],
        }),
      },
      setting.key
    );
  };

  return SP_JSX.jsxs(SP_JSX.Fragment, {
    children: [
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "Emulator",
        children: [
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx("div", {
              style: { opacity: 0.8, fontSize: "0.88em" },
              children:
                error ||
                (block.running
                  ? `Running${block.title ? `: ${block.title}` : ""}. Restart the game to apply.`
                  : "No game running. Edits apply on the next launch."),
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsxs("div", {
              style: { display: "flex", gap: 8, flexWrap: "wrap" },
              children: EMUS.map((item) =>
                SP_JSX.jsx(
                  DFL.ButtonItem,
                  {
                    layout: "below",
                    onClick: () => pickEmu(item.key),
                    children:
                      emu === item.key
                        ? `${item.title} ✓${status?.emus?.[item.key]?.running ? " · live" : ""}`
                        : item.title,
                  },
                  item.key
                )
              ),
            }),
          }),
        ],
      }),
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "Scope",
        children: [
          canPerGame
            ? SP_JSX.jsx(DFL.PanelSectionRow, {
                children: SP_JSX.jsxs("div", {
                  style: { display: "flex", gap: 8, flexWrap: "wrap" },
                  children: [
                    SP_JSX.jsx(DFL.ButtonItem, {
                      layout: "below",
                      onClick: () => setScope("global"),
                      children: scope === "global" ? "Global ✓" : "Global",
                    }),
                    SP_JSX.jsx(DFL.ButtonItem, {
                      layout: "below",
                      onClick: () => setScope("game"),
                      children: scope === "game" ? "This game ✓" : "This game",
                    }),
                  ],
                }),
              })
            : SP_JSX.jsx(DFL.PanelSectionRow, {
                children: SP_JSX.jsx("div", {
                  style: { opacity: 0.75, fontSize: "0.88em" },
                  children: "Cemu quick settings are global (graphic packs still handle resolution).",
                }),
              }),
          canPerGame
            ? SP_JSX.jsx(DFL.PanelSectionRow, {
                children: SP_JSX.jsxs("div", {
                  style: { display: "flex", flexDirection: "column", gap: 6, width: "100%" },
                  children: [
                    SP_JSX.jsx("div", {
                      style: { opacity: 0.85, fontSize: "0.9em" },
                      children: gameName,
                    }),
                    SP_JSX.jsxs("div", {
                      style: { display: "flex", gap: 8, flexWrap: "wrap" },
                      children: [
                        SP_JSX.jsx(DFL.ButtonItem, {
                          layout: "below",
                          disabled: games.length < 2,
                          onClick: () => cycleGame(-1),
                          children: "Prev game",
                        }),
                        SP_JSX.jsx(DFL.ButtonItem, {
                          layout: "below",
                          disabled: games.length < 2,
                          onClick: () => cycleGame(1),
                          children: "Next game",
                        }),
                      ],
                    }),
                  ],
                }),
              })
            : null,
        ],
      }),
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "Quick settings",
        children: settings.length
          ? settings.map(settingRow)
          : [
              SP_JSX.jsx(DFL.PanelSectionRow, {
                children: SP_JSX.jsx("div", {
                  style: { opacity: 0.75 },
                  children: "No config found yet.",
                }),
              }),
            ],
      }),
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "Reset",
        children: [
          canPerGame
            ? SP_JSX.jsx(DFL.PanelSectionRow, {
                children: SP_JSX.jsx(DFL.ButtonItem, {
                  layout: "below",
                  disabled: busy || !effectiveTitle,
                  onClick: () => reset("game"),
                  children: "This game → use global",
                }),
              })
            : null,
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: busy,
              onClick: () => reset("global"),
              children: emu === "cemu" ? "Reset Cemu quick settings" : "Reset global defaults",
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx("div", {
              style: { opacity: 0.7, fontSize: "0.85em" },
              children:
                "Leaves pad binds, dual-screen layout, and Engage 4GB memory alone. Restart after a change.",
            }),
          }),
        ],
      }),
    ],
  });
}

var index = definePlugin(() => ({
  name: "Emu Quick",
  titleView: SP_JSX.jsx("div", {
    className: DFL.staticClasses.Title,
    children: "Emu Quick",
  }),
  content: SP_JSX.jsx(Content, {}),
  icon: SP_JSX.jsx("span", { children: "EQ" }),
}));

export { index as default };
