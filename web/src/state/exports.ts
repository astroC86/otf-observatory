import { getState } from "./store";
import { download } from "../lib/download";
import { csv } from "../lib/csv";
import { notify } from "./uiActions";
import { closeMenu } from "./inspection";
import { saveSession } from "./session";
import { firstChart } from "../components/chart/canvasRegistry";
let rows: readonly object[] = [],
  name = "trace-data";
export function setExport<Row extends object>(next: readonly Row[], filename: string) {
  rows = next;
  name = filename;
}
export function exportCSV() {
  if (!rows.length) return notify("This view has no rows to export.");
  download(name + ".csv", csv(rows), "text/csv");
}
export function exportData(kind: string) {
  if (kind === "csv") exportCSV();
  if (kind === "json") download(name + ".json", JSON.stringify(rows, null, 2));
  if (kind === "session") saveSession();
  if (kind === "png") {
    const canvas = firstChart();
    if (!canvas) return notify("This view has no chart.");
    const anchor = document.createElement("a");
    anchor.download = getState().view + ".png";
    anchor.href = canvas.toDataURL("image/png");
    anchor.click();
  }
  closeMenu();
}
