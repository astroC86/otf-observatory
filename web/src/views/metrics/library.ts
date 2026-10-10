import { getState, updateState } from "../../state/store";
import { scheduleRender } from "../../state/viewActions";
import { notify } from "../../state/uiActions";
import { download } from "../../lib/download";
import { readLibrary } from "./program";
import type { MetricLibrary, MetricProgram } from "./types";

interface ImportedLibrary {
  format: string;
  formulas: MetricLibrary;
}
export function initializeMetricLibrary() {
  try {
    const value = JSON.parse(localStorage.getItem("metricLibrary") || "{}") as MetricLibrary | null;
    updateState({
      metricLibrary: value && typeof value === "object" && !Array.isArray(value) ? value : {},
    });
  } catch {
    updateState({ metricLibrary: {} });
  }
}
function saveLibrary(library: MetricLibrary, message = "") {
  updateState({ metricLibrary: library });
  localStorage.setItem("metricLibrary", JSON.stringify(library));
  if (message) notify(message);
  scheduleRender();
}
export function saveMetric(program: MetricProgram) {
  saveLibrary(
    { ...readLibrary(getState().metricLibrary), [program.name]: structuredClone(program) },
    "Metric saved.",
  );
}
export function loadMetric(name: string) {
  const program = readLibrary(getState().metricLibrary)[name];
  if (program) {
    updateState({ metricProgram: structuredClone(program) });
    scheduleRender();
  }
}
export function deleteMetric(name: string) {
  const library = { ...readLibrary(getState().metricLibrary) };
  delete library[name];
  saveLibrary(library);
}
export function exportLibrary() {
  download(
    "custom-metrics.json",
    JSON.stringify(
      {
        format: "otf-observatory-metrics",
        version: 1,
        formulas: readLibrary(getState().metricLibrary),
      },
      null,
      2,
    ),
  );
}
export async function importLibrary(file: File) {
  if (file.size > 2e6) throw Error("Metric library exceeds 2 MB.");
  const value = JSON.parse(await file.text()) as ImportedLibrary;
  if (
    value.format !== "otf-observatory-metrics" ||
    !value.formulas ||
    Array.isArray(value.formulas) ||
    typeof value.formulas !== "object"
  )
    throw Error("Not a metric library.");
  for (const program of Object.values(value.formulas)) {
    if (
      !program ||
      typeof program.expression !== "string" ||
      !program.sources ||
      typeof program.sources !== "object"
    )
      throw Error("Invalid metric definition.");
  }
  saveLibrary(
    { ...readLibrary(getState().metricLibrary), ...value.formulas },
    "Metric library imported.",
  );
}
