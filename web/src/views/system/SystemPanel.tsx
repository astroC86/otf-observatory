import { inspectObject } from "../../state/inspection";
import { num } from "../../lib/format/numbers";
import { Card } from "../../components/panel/Card";
import { DataTable } from "../../components/table/DataTable";
import { useExport } from "../../hooks/useExport";
import type { TraceMeta } from "../../api/types/common";
import type { DefinitionsResponse } from "../../api/types/data";
import { SystemTree } from "./SystemTree";

export function SystemPanel({
  meta,
  definitions,
}: {
  meta: TraceMeta;
  definitions: DefinitionsResponse;
}) {
  useExport(meta.locations, "system-locations");
  return (
    <>
      <Card
        title="System tree"
        caption={
          <span>{`${num(meta.nodes.length, 0)} system nodes · ${num(meta.groups.length, 0)} location groups · ${num(meta.locations.length, 0)} locations`}</span>
        }
      >
        <SystemTree meta={meta} />
      </Card>
      {definitions.rows.length ? (
        <Card title="Cartesian topologies">
          <DataTable
            id="topology-table"
            rows={definitions.rows}
            columns={[
              { key: "id", label: "Topology ID" },
              {
                key: "data",
                label: "Definition",
                render: (_, row) => JSON.stringify(row.data),
              },
            ]}
            onRow={(row) => inspectObject("Cartesian topology", row.data)}
          />
        </Card>
      ) : null}
    </>
  );
}
