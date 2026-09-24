const manifest = { name: "Playbook" };
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
const runPostUpdate = callable("run_post_update");
const updateTender = callable("update_tender");

function statusLine(status) {
  if (!status) return "Checking playbook…";
  if (status.running) return status.message || "post-update is running.";
  if (status.message) return status.message;
  return "Ready to run post-update (Tender zip + rom-launcher wrap included).";
}

function countsLine(status) {
  if (!status || status.running) return "";
  const ok = status.ok_count ?? 0;
  const warn = status.warn_count ?? 0;
  const fail = status.fail_count ?? 0;
  if (!ok && !warn && !fail) return "";
  return `Last run: ${ok} ok · ${warn} warn · ${fail} fail`;
}

function tenderLine(status) {
  const tender = status?.tender;
  if (!tender) return "Tender: checking wrap…";
  if (tender.running) return tender.message || "Updating Tender + wrap…";
  if (tender.message) return tender.message;
  const ver = tender.installed || "not installed";
  if (tender.wrapped) return `Tender ${ver} · playbook wrap on`;
  return `Tender ${ver} · stock launcher (wrap needed)`;
}

function Content() {
  const [status, setStatus] = SP_REACT.useState(null);
  const [busy, setBusy] = SP_REACT.useState(false);
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

  const jobRunning = Boolean(status?.running || status?.tender?.running);

  const start = async () => {
    if (busy || jobRunning) return;
    setBusy(true);
    try {
      const result = await runPostUpdate();
      toaster.toast({
        title: result?.ok === false ? "Playbook failed" : "Playbook",
        body: (result?.message || "Started post-update").slice(0, 220),
        duration: result?.ok === false ? 7000 : 4000,
      });
      await refresh();
    } catch (err) {
      toaster.toast({
        title: "Playbook failed",
        body: String(err).slice(0, 220),
        duration: 7000,
      });
    } finally {
      setBusy(false);
    }
  };

  const startTender = async () => {
    if (busy || jobRunning) return;
    setBusy(true);
    try {
      const result = await updateTender();
      toaster.toast({
        title: result?.ok === false ? "Tender failed" : "Tender",
        body: (result?.message || "Started Tender update + wrap").slice(0, 220),
        duration: result?.ok === false ? 7000 : 4000,
      });
      await refresh();
    } catch (err) {
      toaster.toast({
        title: "Tender failed",
        body: String(err).slice(0, 220),
        duration: 7000,
      });
    } finally {
      setBusy(false);
    }
  };

  const manual = Array.isArray(status?.manual) ? status.manual : [];

  return SP_JSX.jsxs(SP_JSX.Fragment, {
    children: [
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "After SteamOS update",
        children: [
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx("div", {
              style: { opacity: 0.75, fontSize: "0.88em" },
              children: error || statusLine(status),
            }),
          }),
          countsLine(status)
            ? SP_JSX.jsx(DFL.PanelSectionRow, {
                children: SP_JSX.jsx("div", {
                  style: { opacity: 0.75, fontSize: "0.88em" },
                  children: countsLine(status),
                }),
              })
            : null,
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: busy || jobRunning,
              onClick: start,
              children: status?.running ? "Running…" : "Run post-update",
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: busy,
              onClick: refresh,
              children: "Refresh status",
            }),
          }),
        ],
      }),
      SP_JSX.jsxs(DFL.PanelSection, {
        title: "Tender",
        children: [
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx("div", {
              style: { opacity: 0.75, fontSize: "0.88em" },
              children: tenderLine(status),
            }),
          }),
          SP_JSX.jsx(DFL.PanelSectionRow, {
            children: SP_JSX.jsx(DFL.ButtonItem, {
              layout: "below",
              disabled: busy || jobRunning,
              onClick: startTender,
              children: status?.tender?.running
                ? "Updating Tender…"
                : "Update Tender + wrap",
            }),
          }),
        ],
      }),
      manual.length
        ? SP_JSX.jsxs(DFL.PanelSection, {
            title: "Manual leftover",
            children: [
              SP_JSX.jsx(DFL.PanelSectionRow, {
                children: SP_JSX.jsx("div", {
                  style: {
                    opacity: 0.8,
                    fontSize: "0.82em",
                    whiteSpace: "pre-wrap",
                  },
                  children: manual.join("\n").slice(0, 900),
                }),
              }),
            ],
          })
        : null,
    ],
  });
}

var index = definePlugin(() => ({
  name: "Playbook",
  titleView: SP_JSX.jsx("div", {
    className: DFL.staticClasses.Title,
    children: "Playbook",
  }),
  content: SP_JSX.jsx(Content, {}),
  icon: SP_JSX.jsx("span", { children: "P" }),
}));

export { index as default };
