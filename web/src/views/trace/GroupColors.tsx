import { useMemo } from "react";
import { groupColor } from "../../state/selectors";
import { persistState } from "../../state/persistence";
import { ControlBar } from "../../components/controls/ControlBar";
import type { ControlSpec } from "../../components/controls/types";
import { updateState } from "../../state/store";
import { useStore } from "../../state/useStore";
import type { TraceMeta } from "../../api/types/common";

export function GroupColors({ meta }: { meta: TraceMeta }) {
  const colors = useStore((snapshot) => snapshot.colors);
  const groups = useMemo(
    () => [...new Set(meta.regions.map((region) => region.group))],
    [meta.regions],
  );
  return (
    <ControlBar
      id="color-settings"
      controls={groups.map<ControlSpec>((group) => ({
        kind: "color",
        className: "color-input",
        data: { "color-group": group },
        label: `${group ?? ""}`,
        labelAfter: true,
        value: groupColor(group, colors),
        event: "input",
        onChange: (value) => {
          updateState((previous) => ({
            colors: { ...previous.colors, [group]: value },
          }));
          persistState("colors");
        },
      }))}
    />
  );
}
