import { useEffect } from "react";
import { getState, getUi, updateState } from "../state/store";
import { loadTrace } from "../state/trace/load";
import { beginTraceLoad, isCurrentTraceLoad } from "../state/trace/requests";
import { setRange } from "../state/rangeActions";
import { setView } from "../state/viewActions";
import { panelSettings, restoreSettings } from "./settings";

function selection() {
  const { id, start, end, locations, region, exclude, group } = getState();
  return { traceId: id, start, end, locations: [...locations], region, exclude, group };
}

export function useEmbed(initialized: boolean): void {
  useEffect(() => {
    if (!initialized || !getUi().embedded) return;
    let pending: Record<string, unknown> | undefined;
    let loadingRequest: number | undefined;
    let applying = false;
    let ready = false;
    let mounted = true;
    let lastSelection = "";
    let lastSettings = "";
    const defaults = panelSettings();
    delete defaults.view; // The panel URL, not defaults, selects its view.
    const send = (message: object) => {
      if (mounted) window.parent.postMessage(message, location.origin);
    };

    async function drain(): Promise<void> {
      if (!mounted || applying) return;
      applying = true;
      try {
        while (mounted && pending) {
          const data = pending;
          pending = undefined;
          const { traceId, start, end } = data;
          if (
            typeof traceId !== "string" ||
            !traceId ||
            typeof start !== "number" ||
            !Number.isFinite(start) ||
            typeof end !== "number" ||
            !Number.isFinite(end) ||
            end < start
          )
            continue;
          if (getState().id !== traceId) {
            loadingRequest = beginTraceLoad();
            await loadTrace(traceId, undefined, loadingRequest);
            loadingRequest = undefined;
            if (!mounted) return;
          }
          const meta = getState().meta;
          if (!meta || getState().id !== traceId) continue;
          if (data.initialize && data.settings !== null && typeof data.settings === "object") {
            updateState(restoreSettings(defaults, data.settings));
            const state = getState();
            const metric = meta.metrics.some((item) => item.id === state.metric)
              ? state.metric
              : meta.metrics[0]?.id || "";
            updateState({
              metric,
              metricY: meta.metrics.some((item) => item.id === state.metricY)
                ? state.metricY
                : meta.metrics[1]?.id || metric,
              detailLocation:
                state.detailLocation &&
                !meta.locations.some((item) => item.id === state.detailLocation)
                  ? null
                  : state.detailLocation,
              view: state.view === "workspace" ? "timeline" : state.view,
            });
            setView(getState().view);
            lastSettings = JSON.stringify(panelSettings());
          }
          const locations = Array.isArray(data.locations)
            ? data.locations
                .map(String)
                .filter((id) => meta.locations.some((item) => item.id === id))
            : meta.locations.map((item) => item.id);
          updateState({
            locations: new Set(locations),
            region: String(data.region || ""),
            exclude: String(data.exclude || ""),
            group: String(data.group || ""),
          });
          setRange(start, end);
          lastSelection = JSON.stringify(selection());
          ready = true;
        }
      } catch (error) {
        send({
          type: "otf-dock-error",
          message: error instanceof Error ? error.message : String(error),
        });
      } finally {
        loadingRequest = undefined;
        applying = false;
        if (mounted && pending) queueMicrotask(drain);
      }
    }

    function message(event: MessageEvent<unknown>): void {
      if (event.origin !== location.origin || event.source !== window.parent) return;
      const incoming = event.data;
      if (
        incoming === null ||
        typeof incoming !== "object" ||
        !("type" in incoming) ||
        incoming.type !== "otf-dock-state"
      )
        return;
      const data = incoming as Record<string, unknown>;
      const prior = pending?.traceId === data.traceId ? pending : undefined;
      pending = { ...prior, ...data };
      if (prior?.initialize && !data.initialize) {
        pending.initialize = true;
        pending.settings = prior.settings;
      }
      void drain();
    }

    function changed(): void {
      if (!ready || applying || !getState().meta) return;
      const data = selection();
      const signature = JSON.stringify(data);
      if (signature !== lastSelection) {
        lastSelection = signature;
        send({ type: "otf-dock-selection", ...data });
      }
      const settings = panelSettings();
      const json = JSON.stringify(settings);
      if (json !== lastSettings) {
        lastSettings = json;
        send({ type: "otf-dock-panel-state", settings });
      }
    }

    window.addEventListener("message", message);
    window.addEventListener("otf-selection-changed", changed);
    send({ type: "otf-dock-ready" });
    return () => {
      mounted = false;
      pending = undefined;
      window.removeEventListener("message", message);
      window.removeEventListener("otf-selection-changed", changed);
      if (loadingRequest !== undefined && isCurrentTraceLoad(loadingRequest)) beginTraceLoad();
    };
  }, [initialized]);
}
