import { useMemo } from "react";
import { compact, num } from "../../lib/format/numbers";
import { duration } from "../../lib/format/time";
import { inspectObject } from "../../state/inspection";
import { useExport } from "../../hooks/useExport";
import { Card } from "../../components/panel/Card";
import { DataTable } from "../../components/table/DataTable";
import { StatGrid } from "../../components/ui/StatGrid";
import type { ViewState } from "../../state/types";
import type { FunctionSummaryRow } from "../../api/types/execution";
import { change } from "../executionState";
import { functionColumns, type GroupedFunctionRow } from "./columns";
import { selectControl } from "../../components/controls/factories";

export function FunctionsPanel({
  rows,
  state,
}: {
  rows: readonly FunctionSummaryRow[];
  state: ViewState;
}) {
  const { data, total, calls } = useMemo(() => {
    let summary: readonly (FunctionSummaryRow | GroupedFunctionRow)[] = rows;
    if (state.groupBy === "group") {
      const grouped: Record<string, Omit<GroupedFunctionRow, "average">> = {};
      for (const row of rows) {
        const group = (grouped[row.group] ??= {
          id: row.group,
          name: row.group,
          group: row.group,
          calls: 0,
          overlapping: 0,
          inclusive: 0,
          exclusive: 0,
          minimum: Infinity,
          maximum: 0,
          estimated: 0,
        });
        for (const key of ["calls", "overlapping", "inclusive", "exclusive", "estimated"] as const)
          group[key] += row[key];
        group.minimum = Math.min(group.minimum, row.minimum);
        group.maximum = Math.max(group.maximum, row.maximum);
      }
      summary = Object.values(grouped)
        .map((row) => ({ ...row, average: row.inclusive / row.overlapping }))
        .toSorted((a, b) => b.exclusive - a.exclusive);
    }
    const total = summary.reduce((sum, row) => sum + row.exclusive, 0);
    const calls = summary.reduce((sum, row) => sum + row.calls, 0);
    return {
      total,
      calls,
      data: summary.map((row) => ({
        ...row,
        share: (row.exclusive / Math.max(total, 1e-30)) * 100,
      })),
    };
  }, [rows, state.groupBy]);
  useExport(data, "function-summary");
  return (
    <>
      <StatGrid
        items={[
          {
            label: "Accumulated exclusive time",
            value: duration(total),
            detail: "Across selected locations",
          },
          {
            label: "Calls entered",
            value: compact(calls),
            detail: "Within the selected interval",
          },
          {
            label: state.groupBy === "group" ? "Function groups" : "Functions",
            value: num(data.length, 0),
            detail: "Intersecting this interval",
          },
          {
            label: "Top contributor",
            value: `${num(((data[0]?.exclusive || 0) / Math.max(total, 1e-30)) * 100, 1)}%`,
            detail: data[0]?.name || "—",
            truncateDetail: true,
          },
        ]}
      />
      <Card
        title="Function summary"
        controls={[
          selectControl(
            "function-group-by",
            undefined,
            state.groupBy,
            [
              ["function", "Individual functions"],
              ["group", "Function groups"],
            ],
            (value) => change({ groupBy: value }),
            {
              ariaLabel: "Group function summary",
            },
          ),
        ]}
        caption={
          <span>{`Inclusive and exclusive times are clipped to the selection. Calls counts entries, overlapping counts intersecting calls.`}</span>
        }
      >
        <DataTable
          id="function-table"
          rows={data}
          columns={functionColumns}
          onRow={(row) => inspectObject(row.name, row)}
        />
      </Card>
    </>
  );
}
