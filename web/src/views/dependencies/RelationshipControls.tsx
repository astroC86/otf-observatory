import { useState } from "react";
import { ControlBar } from "../../components/controls/ControlBar";
import { buttonControl, checkboxControl, selectControl } from "../../components/controls/factories";
import type { ViewState } from "../../state/types";
import { updateQuery } from "../shared/dataControls";

export function RelationshipControls({
  snapshot,
  kinds,
}: {
  snapshot: ViewState;
  kinds: readonly string[];
}) {
  const [draft, setDraft] = useState(() => snapshot.relationshipSearch);
  return (
    <ControlBar
      controls={[
        selectControl(
          "relationship-kind",
          "Activity",
          snapshot.relationshipKind[snapshot.view] || "",
          [["", "All activities"], ...kinds],
          (value) =>
            updateQuery((previous) => ({
              relationshipKind: { ...previous.relationshipKind, [snapshot.view]: value },
              analysisPage: 0,
              relationshipOffset: 0,
            })),
        ),
        {
          kind: "search",
          id: "relationship-search",
          label: "Find lock, task, event or stream",
          value: draft,
          onChange: setDraft,
        },
        buttonControl("relationship-filter", "Filter", () =>
          updateQuery({ relationshipSearch: draft, analysisPage: 0, relationshipOffset: 0 }),
        ),
        checkboxControl(
          "relationship-edges",
          "Dependency arrows",
          snapshot.relationshipEdges !== false,
          (checked) => updateQuery({ relationshipEdges: checked }),
          { labelAfter: true, labelClassName: "check" },
        ),
      ]}
    />
  );
}
