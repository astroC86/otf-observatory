import { useState } from "react";
import { inspectObject } from "../../state/inspection";
import { num } from "../../lib/format/numbers";
import { ControlBar } from "../../components/controls/ControlBar";
import { DataTable } from "../../components/table/DataTable";
import type { ColumnDef } from "../../components/table/types";
import { useExport } from "../../hooks/useExport";
import type { ViewState } from "../../state/types";
import type { DefinitionRow, DefinitionsResponse } from "../../api/types/data";
import { pageButton, updateQuery } from "../shared/dataControls";
import { selectControl, buttonControl } from "../../components/controls/factories";

const definitionColumns: ColumnDef<DefinitionRow>[] = [
  { key: "kind", label: "Definition" },
  { key: "id", label: "ID" },
  {
    key: "data",
    label: "Fields",
    render: (_, row) => <span className="definition-data">{`${JSON.stringify(row.data)}`}</span>,
  },
];

export function DefinitionBrowser({
  definitions,
  snapshot,
}: {
  definitions: DefinitionsResponse;
  snapshot: ViewState;
}) {
  useExport(definitions.rows, "trace-definitions");
  const [search, setSearch] = useState(snapshot.definitionSearch);
  return (
    <>
      <ControlBar
        controls={[
          selectControl(
            "definition-kind",
            "Definition",
            snapshot.definitionKind,
            [["", "All definitions"], ...definitions.kinds],
            (value) => updateQuery({ definitionKind: value, definitionOffset: 0 }),
          ),
          {
            kind: "text",
            id: "definition-search",
            label: "Search",
            value: search,
            onChange: setSearch,
          },
          buttonControl("definition-apply", "Search", () =>
            updateQuery({ definitionSearch: search, definitionOffset: 0 }),
          ),
          {
            kind: "content",
            children: <span>{`${num(definitions.total, 0)} results`}</span>,
          },
          pageButton(
            "definition-prev",
            "definitionOffset",
            -300,
            (snapshot.definitionOffset || 0) === 0,
          ),
          pageButton(
            "definition-next",
            "definitionOffset",
            300,
            (snapshot.definitionOffset || 0) + 300 >= definitions.total,
          ),
        ]}
      />
      <DataTable
        id="definition-table"
        rows={definitions.rows}
        columns={definitionColumns}
        onRow={(row) => inspectObject(row.kind, row)}
      />
    </>
  );
}
