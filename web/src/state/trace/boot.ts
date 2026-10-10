import { api } from "../../api/client";
import type { TraceListing } from "../../api/types/common";
import { updateUi } from "../store";
import { notify } from "../uiActions";
import { currentTraceLoad, isCurrentTraceLoad } from "./requests";
import { openTrace } from "./open";
export async function boot(): Promise<void> {
  const request = currentTraceLoad();
  try {
    const traces = await api<TraceListing[]>("traces");
    if (!isCurrentTraceLoad(request)) return;
    updateUi({ traces });
    const last = localStorage.getItem("lastTrace");
    const initial =
      traces.find((trace) => trace.id === last) ||
      traces.find((trace) => trace.path.includes("run-396831")) ||
      traces[0];
    if (initial) await openTrace({ id: initial.id });
  } catch (error) {
    notify(error instanceof Error ? error.message : String(error));
  }
}
