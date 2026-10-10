import { useMemo } from "react";
import { duration } from "../../lib/format/time";
import { num } from "../../lib/format/numbers";
import { setView } from "../../state/viewActions";
import { updateState } from "../../state/store";
import { useExport } from "../../hooks/useExport";
import { Card } from "../../components/panel/Card";
import { Chart } from "../../components/chart/Chart";
import { DataTable } from "../../components/table/DataTable";
import { StatGrid } from "../../components/ui/StatGrid";
import type { ProcessSummaryRow } from "../../api/types/execution";
import { processColumns } from "./columns";

export function ProcessesPanel({ all }: { all: readonly ProcessSummaryRow[] }) {
  const { rows, average, maximum, minimum } = useMemo(() => {
    const rows = all.filter((row) => row.type !== "METRIC");
    const values = rows.map((row) => row.exclusive);
    return {
      rows,
      average: values.reduce((sum, value) => sum + value, 0) / Math.max(values.length, 1),
      maximum: Math.max(0, ...values),
      minimum: Math.min(...values),
    };
  }, [all]);
  useExport(rows, "process-summary");
  return (
    <>
      <StatGrid
        details={false}
        items={[
          { label: "Execution locations", value: num(rows.length, 0) },
          { label: "Mean recorded activity", value: duration(average) },
          {
            label: "Maximum / mean",
            value: `${num(maximum / Math.max(average, 1e-30), 3)}×`,
          },
          {
            label: "Range of activity",
            value: duration(maximum - (isFinite(minimum) ? minimum : 0)),
          },
        ]}
      />
      <Card
        title="Time by location & function group"
        caption={
          <span>{`First 36 execution locations are charted; all locations appear below. Click a bar for its timeline. Recorded activity includes waits.`}</span>
        }
      >
        <Chart
          id="process-chart"
          aria-label="Process time by function group"
          spec={{ type: "processes", data: rows }}
        />
      </Card>
      <Card title="Location statistics">
        <DataTable
          id="process-table"
          rows={rows}
          columns={processColumns}
          onRow={(row) => {
            updateState({ detailLocation: row.id });
            setView("timeline");
          }}
        />
      </Card>
    </>
  );
}
