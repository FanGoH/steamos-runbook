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
const applyLive = callable("apply_live");
const saveSettings = callable("save_settings");
const resetSettings = callable("reset_settings");

const EMUS = [
  { key: "eden", title: "Eden" },
  { key: "azahar", title: "Azahar" },
  { key: "cemu", title: "Cemu" },
];

function displayOf(setting, value) {
  const options = setting?.options || [];
  const match = options.find((opt) => opt.value === String(value));
  if (match) return match.label;
  if (setting?.kind === "bool") return value === "true" ? "On" : "Off";
  return value;
}

function optionIndex(setting, value) {
  const options = setting?.options || [];
  const idx = options.findIndex((opt) => opt.value === String(value));
  return idx < 0 ? 0 : idx;
}

function Content() {
  const [status, setStatus] = SP_REACT.useState(null);
  const [emu, setEmu] = SP_REACT.useState("eden");
  const [scope, setScope] = SP_REACT.useState("global");
  const [titleId, setTitleId] = SP_REACT.useState("");
  const [busy, setBusy] = SP_REACT.useState(false);
  const [error, setError] = SP_REACT.useState("");
  const [draft, setDraft] = SP_REACT.useState({});
  const emuTouched = SP_REACT.useRef(false);
  const titleTouched = SP_REACT.useRef(false);
  const liveTimers = SP_REACT.useRef({});

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
  const diskSettings = block.settings || [];
  const canPerGame = block.per_game !== false && emu !== "cemu";
  const effectiveTitle = titleId || block.title_id || "";
  const gameName =
    (games.find((g) => g.id === effectiveTitle) || {}).name ||
    block.title ||
    effectiveTitle ||
    "No game selected";

  const settings = diskSettings.map((setting) => {
    if (draft[setting.key] === undefined) return setting;
    const value = String(draft[setting.key]);
    return {
      ...setting,
      value,
      display: displayOf(setting, value),
    };
  });

  const dirtyEntries = {};
  for (const setting of diskSettings) {
    if (draft[setting.key] !== undefined && String(draft[setting.key]) !== String(setting.value)) {
      dirtyEntries[setting.key] = String(draft[setting.key]);
    }
  }
  const dirty = Object.keys(dirtyEntries).length > 0;

  const toastSave = (result) => {
    const body = (result?.messages || [result?.message || ""])
      .filter(Boolean)
      .join(" ")
      .slice(0, 220);
    toaster.toast({
      title: result?.ok === false ? "Save failed" : "Saved",
      body: body || "Saved this game's settings.",
      duration: result?.ok === false ? 7000 : 4000,
    });
  };

  const pickEmu = (key) => {
    emuTouched.current = true;
    titleTouched.current = false;
    setEmu(key);
    setTitleId("");
    setScope("global");
    setDraft({});
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
    setDraft({});
    refresh({ emu, title: next });
  };

  const queueLive = (setting, value) => {
    if (setting.hotswap !== "live" || !block.running) return;
    const key = setting.key;
    if (liveTimers.current[key]) clearTimeout(liveTimers.current[key]);
    const delay = setting.widget === "toggle" ? 0 : 280;
    liveTimers.current[key] = setTimeout(async () => {
      try {
        const result = await applyLive(
          emu,
          canPerGame ? scope : "global",
          effectiveTitle,
          key,
          String(value)
        );
        if (result?.ok === false) {
          toaster.toast({
            title: "Live apply failed",
            body: String(result.message || "Could not send Eden hotkey").slice(0, 220),
            duration: 5000,
          });
        }
      } catch (err) {
        toaster.toast({
          title: "Live apply failed",
          body: String(err).slice(0, 220),
          duration: 5000,
        });
      }
    }, delay);
  };

  const changeSetting = (setting, value) => {
    const next = String(value);
    setDraft((prev) => ({ ...prev, [setting.key]: next }));
    queueLive(setting, next);
  };

  const save = async () => {
    if (busy || !dirty) return;
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
      const result = await saveSettings(
        emu,
        canPerGame ? scope : "global",
        effectiveTitle,
        JSON.stringify(dirtyEntries)
      );
      toastSave(result);
      setDraft({});
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
      toastSave(result);
      setDraft({});
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
    const extra = [];
    if (canPerGame && setting.use_global === false) extra.push("this game");
    if (setting.hotswap === "live") extra.push("live");
    if (draft[setting.key] !== undefined && draft[setting.key] !== diskSettings.find((s) => s.key === setting.key)?.value)
      extra.push("unsaved");
    const badge = extra.length ? ` · ${extra.join(" · ")}` : "";
    const widget = setting.widget || (setting.kind === "bool" ? "toggle" : "slider");
    if (widget === "toggle" && DFL.ToggleField) {
      return SP_JSX.jsx(
        DFL.PanelSectionRow,
        {
          children: SP_JSX.jsx(DFL.ToggleField, {
            label: setting.label + badge,
            checked: setting.value === "true",
            disabled: busy,
            onChange: (on) => changeSetting(setting, on ? "true" : "false"),
          }),
        },
        setting.key
      );
    }
    const options = setting.options || [];
    if (widget === "slider" && DFL.SliderField && options.length) {
      return SP_JSX.jsx(
        DFL.PanelSectionRow,
        {
          children: SP_JSX.jsx(DFL.SliderField, {
            label: `${setting.label}: ${setting.display || setting.value}${badge}`,
            min: 0,
            max: options.length - 1,
            step: 1,
            value: optionIndex(setting, setting.value),
            notchCount: Math.min(options.length, 9),
            showValue: false,
            disabled: busy,
            onChange: (idx) => {
              const next = options[Math.max(0, Math.min(options.length - 1, Math.round(idx)))];
              if (next) changeSetting(setting, next.value);
            },
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
                  onClick: () =>
                    changeSetting(
                      setting,
                      options[Math.max(0, optionIndex(setting, setting.value) - 1)]?.value
                    ),
                  children: "−",
                }),
                SP_JSX.jsx(DFL.ButtonItem, {
                  layout: "below",
                  disabled: busy,
                  onClick: () =>
                    changeSetting(
                      setting,
                      options[Math.min(options.length - 1, optionIndex(setting, setting.value) + 1)]?.value
                    ),
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
                  ? `Running${block.title ? `: ${block.title}` : ""}. Live rows apply now; Save writes this game.`
                  : "No game running. Save writes settings for the next launch."),
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
                      onClick: () => {
                        setScope("global");
                        setDraft({});
                      },
                      children: scope === "global" ? "Global ✓" : "Global",
                    }),
                    SP_JSX.jsx(DFL.ButtonItem, {
                      layout: "below",
                      onClick: () => {
                        setScope("game");
                        setDraft({});
                      },
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
        title: "Save",
        children: [
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: busy || !dirty,
              onClick: save,
              children: dirty ? "Save this game" : "Saved",
            }),
          }),
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
                "Live rows (docked, filter, GPU Normal/High, speed limit) apply in Eden now and stay unsaved until Save. Resolution still needs an Eden restart after Save.",
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
