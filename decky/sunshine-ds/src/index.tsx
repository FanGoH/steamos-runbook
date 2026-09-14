import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useEffect, useState } from "react";

type Status = {
  ok: boolean;
  gamescope: boolean;
  plasma: boolean;
  ds: string;
  headline: string;
  detail: string;
};

type ActionResult = { ok: boolean; message?: string };

const getStatus = callable<[], Status>("get_status");
const startDesktopDs = callable<[], ActionResult>("start_desktop_ds");

function Content() {
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
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
        title: result.ok ? "Switching" : "Failed",
        body: (result.message || "").slice(0, 220),
        duration: result.ok ? 4000 : 7000,
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

  return (
    <>
      <PanelSection title="Proven sunshine-ds">
        <PanelSectionRow>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ fontSize: "1.15em", fontWeight: 600 }}>
              {status?.headline ?? "Loading…"}
            </div>
            <div style={{ opacity: 0.75, fontSize: "0.92em" }}>
              {status?.detail ?? ""}
            </div>
            <div style={{ opacity: 0.55, fontSize: "0.85em" }}>
              {status
                ? `gamescope ${status.gamescope ? "up" : "down"} · plasma ${
                    status.plasma ? "up" : "down"
                  } · :48100 ${status.ds}`
                : ""}
            </div>
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy} onClick={start}>
            Start Dual-Stream Desktop
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Moonlight">
        <PanelSectionRow>
          <div style={{ opacity: 0.65, fontSize: "0.88em" }}>
            This plugin does not launch games. After Plasma is up, connect Thor/Odin
            to :48100 and use Desktop, Cemu Dual-Screen, or Azahar Dual-Screen.
            Return to Game Mode is a Sunshine app (teardown).
          </div>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => ({
  name: "Sunshine DS",
  titleView: <div className={staticClasses.Title}>Sunshine DS</div>,
  content: <Content />,
  icon: <span>DS</span>,
}));
