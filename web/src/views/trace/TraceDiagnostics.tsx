import { useMemo } from "react";
import { num } from "../../lib/format/numbers";
import { setView } from "../../state/viewActions";
import { Card } from "../../components/panel/Card";
import { DataTable } from "../../components/table/DataTable";
import { countCol } from "../../components/table/columns";
import { useExport } from "../../hooks/useExport";
import { updateState } from "../../state/store";
import type { TraceMeta } from "../../api/types/common";
import type { EventTypeCountRow } from "../../api/types/data";
import { GroupColors } from "./GroupColors";

export function TraceDiagnostics({ meta }: { meta: TraceMeta }) {
  const types = useMemo<EventTypeCountRow[]>(
    () => Object.entries(meta.eventTypes).map(([kind, count]) => ({ kind, count })),
    [meta.eventTypes],
  );
  useExport(types, "event-type-counts");
  return (
    <>
      <Card title="Validation diagnostics">
        {Object.keys(meta.warnings).length ? (
          <ul className="warning-list">
            {Object.entries(meta.warnings).map(([name, count]) => (
              <li key={name}>{`${name}: ${num(count, 0)}`}</li>
            ))}
          </ul>
        ) : (
          <div className="properties">
            <p
              style={{ paddingTop: 18 }}
            >{`No importer diagnostics were recorded for this archive.`}</p>
          </div>
        )}
      </Card>
      <Card title="Event record types">
        <DataTable
          id="record-types"
          rows={types}
          columns={[{ key: "kind", label: "Event" }, countCol<EventTypeCountRow>("count", "Count")]}
          onRow={(row) => {
            updateState({ eventKind: row.kind });
            setView("events");
          }}
          maxHeight={350}
        />
      </Card>
      <Card title="Function group colors">
        <GroupColors meta={meta} />
      </Card>
    </>
  );
}
