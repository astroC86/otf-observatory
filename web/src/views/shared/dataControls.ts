import { scheduleRender } from "../../state/viewActions";
import type { ControlSpec } from "../../components/controls/types";
import { updateState } from "../../state/store";
import type { StatePatch } from "../../state/types";

export function updateQuery(patch: StatePatch) {
  updateState(patch);
  scheduleRender();
}

type PageField =
  | "messageOffset"
  | "eventOffset"
  | "definitionOffset"
  | "relationshipOffset"
  | "gpuExternalOffset"
  | "analysisPage";
export function pageButton(
  id: string,
  field: PageField,
  step: number,
  disabled: boolean,
): ControlSpec {
  return {
    kind: "button",
    id,
    disabled,
    children: step < 0 ? "←" : "→",
    onClick: () =>
      updateQuery((previous) => ({
        [field]: Math.max(0, (previous[field] || 0) + step),
      })),
  };
}
