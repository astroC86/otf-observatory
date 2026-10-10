import { useState } from "react";
import { ControlBar } from "../../components/controls/ControlBar";
import type { ViewState } from "../../state/types";
import { updateQuery } from "../shared/dataControls";
import { selectControl, buttonControl } from "../../components/controls/factories";

export function EventFilters({ snapshot }: { snapshot: ViewState }) {
  const [search, setSearch] = useState(snapshot.eventSearch);
  const applySearch = () => updateQuery({ eventSearch: search, eventOffset: 0 });
  return (
    <ControlBar
      controls={[
        selectControl(
          "event-kind",
          "Event type",
          snapshot.eventKind,
          [["", "All record types"], ...Object.keys(snapshot.meta.eventTypes)],
          (value) => updateQuery({ eventKind: value, eventOffset: 0 }),
        ),
        {
          kind: "text",
          id: "event-search",
          label: "Search",
          value: search,
          placeholder: "Record type or raw fields",
          onChange: setSearch,
          onKeyDown: (event) => {
            if (event.key === "Enter") applySearch();
          },
        },
        buttonControl("apply-event-search", "Search", applySearch),
      ]}
    />
  );
}
