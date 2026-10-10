import type { ReactNode } from "react";
import { getUi, updateState, updateUi } from "./store";
import { query } from "../api/client";
import { setRange } from "./rangeActions";
import { scheduleRender } from "./viewActions";
import { addBookmark } from "./bookmarks";
import { regions } from "./selectors";
import { notify } from "./uiActions";
import type { SpanResponse, MenuRow } from "../api/types/common";
import type { InspectorContent, UiState } from "./types";

export async function inspectSpan(id: number | string | undefined) {
  if (!id) return;
  try {
    const span = await query<SpanResponse>("span", { span: id });
    updateState({ selectedRegion: span.region });
    updateUi({ context: { kind: "span", span }, contextVisible: true });
  } catch (error) {
    notify(error instanceof Error ? error.message : String(error));
  }
}
export function inspectObject(title: unknown, object: unknown, content?: InspectorContent): void {
  updateUi({
    context: { kind: "object", title: String(title ?? ""), object, ...content },
    contextVisible: true,
  });
}
export function inspectContent(title: string, content: ReactNode): void {
  updateUi({
    context: { kind: "content", title, content },
    contextVisible: true,
  });
}
export function showMenu(event: Pick<MouseEvent, "clientX" | "clientY">, row: object) {
  updateUi({
    menu: {
      row,
      left: Math.min(event.clientX, innerWidth - 200),
      top: Math.min(event.clientY, innerHeight - 200),
    },
  });
}
export function closeMenu() {
  if (getUi().menu) updateUi({ menu: null });
}
export function showExportMenu(event: Pick<MouseEvent, "clientX" | "clientY">) {
  updateUi({
    menu: {
      export: true,
      left: Math.min(event.clientX, innerWidth - 260),
      top: event.clientY + 15,
    },
  });
}
export function contextAction(action: string, value: object) {
  const row = value as MenuRow;
  closeMenu();
  if (action === "context") void inspectSpan(row.id);
  if (action === "zoom") setRange(row.start!, row.end!);
  if (action === "function") {
    updateState({ region: regions[row.region!]?.name || "" });
    scheduleRender();
  }
  if (action === "location") {
    updateState({ locations: new Set([row.location!]) });
    scheduleRender();
  }
  if (action === "bookmark") {
    setRange(row.start!, row.end!);
    addBookmark();
  }
}
export function setTooltip(
  event: Pick<MouseEvent, "clientX" | "clientY">,
  content: ReactNode,
): void {
  updateUi({
    tooltip:
      content == null || content === false || content === ""
        ? null
        : { content, x: event.clientX, y: event.clientY },
  });
}
export function setBrush(brush: UiState["brush"]) {
  updateUi({ brush });
}
