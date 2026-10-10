import { useMemo, useReducer, type CSSProperties } from "react";
import { color } from "../../state/selectors";
import { inspectObject } from "../../state/inspection";
import { updateState } from "../../state/store";
import { useStore } from "../../state/useStore";
import { useExport } from "../../hooks/useExport";
import { Card } from "../../components/panel/Card";
import { Chart } from "../../components/chart/Chart";
import { ControlBar } from "../../components/controls/ControlBar";
import { DataTable } from "../../components/table/DataTable";
import { countCol, timeCol } from "../../components/table/columns";
import type { ColumnDef } from "../../components/table/types";
import type { CallTreeRow } from "../../api/types/execution";
import { change } from "../executionState";
import { selectControl, buttonControl } from "../../components/controls/factories";

type VisibleCallTreeRow = CallTreeRow & { visualDepth: number };
export function CallTreePanel({ rows, mode }: { rows: readonly CallTreeRow[]; mode: string }) {
  const collapsed = useStore((state) => state.collapsed);
  const [revision, redraw] = useReducer((value: number) => value + 1, 0);
  const children = useMemo(() => {
    const grouped = new Map<number, CallTreeRow[]>();
    if (mode !== "flame") {
      for (const row of rows) {
        const siblings = grouped.get(row.parent);
        if (siblings) siblings.push(row);
        else grouped.set(row.parent, [row]);
      }
      for (const [parent, siblings] of grouped)
        grouped.set(
          parent,
          siblings.toSorted((a, b) => b.inclusive - a.inclusive),
        );
    }
    return grouped;
  }, [rows, mode]);
  const shown = useMemo(() => {
    const result: VisibleCallTreeRow[] = [];
    function walk(parent: number, depth: number) {
      for (const row of children.get(parent) || []) {
        result.push({ ...row, visualDepth: depth });
        if (!collapsed.has(row.id)) walk(row.id, depth + 1);
      }
    }
    walk(0, 0);
    return result;
  }, [children, collapsed]);
  const columns = useMemo<readonly ColumnDef<VisibleCallTreeRow>[]>(
    () => [
      {
        key: "name",
        label: "Calling path",
        render: (_value, row) => (
          <>
            <span
              className="tree-indent"
              style={{ "--indent": `${row.visualDepth * 17}px` } as CSSProperties}
            />
            <ControlBar
              className={null}
              controls={[
                {
                  kind: "button",
                  className: "tree-toggle",
                  data: { tree: row.id },
                  ariaLabel: `${collapsed.has(row.id) ? "Expand" : "Collapse"} ${row.name}`,
                  children: children.get(row.id)?.length
                    ? collapsed.has(row.id)
                      ? "▸"
                      : "▾"
                    : "·",
                  onClick: (event) => {
                    event.stopPropagation();
                    updateState((previous) => {
                      const next = new Set(previous.collapsed);
                      if (next.has(row.id)) next.delete(row.id);
                      else next.add(row.id);
                      return { collapsed: next };
                    });
                    redraw();
                  },
                },
              ]}
            />
            <i className="swatch" style={{ background: color(row.region) }} />
            {` ${row.name ?? ""}`}
          </>
        ),
      },
      countCol<VisibleCallTreeRow>("calls", "Calls entered"),
      countCol<VisibleCallTreeRow>("overlapping", "Overlapping"),
      timeCol<VisibleCallTreeRow>("inclusive", "Inclusive"),
      timeCol<VisibleCallTreeRow>("exclusive", "Exclusive"),
    ],
    [children, collapsed],
  );
  useExport(rows, "call-tree");
  return (
    <Card
      title="Call tree"
      controls={[
        selectControl(
          "call-mode",
          undefined,
          mode,
          [
            ["tree", "Tree table"],
            ["flame", "Flame graph"],
          ],
          (value) => change({ callMode: value }),
          {
            ariaLabel: "Call tree display",
          },
        ),
        buttonControl(
          "expand-tree",
          "Expand all",
          mode === "flame"
            ? undefined
            : () => {
                updateState({ collapsed: new Set<number>() });
                redraw();
              },
        ),
        buttonControl(
          "collapse-tree",
          "Collapse all",
          mode === "flame"
            ? undefined
            : () => {
                updateState((previous) => ({
                  collapsed: new Set([...previous.collapsed, ...rows.map((row) => row.id)]),
                }));
                redraw();
              },
        ),
      ]}
      caption={
        <span>{`Paths preserve recursion and ancestor context. Flame widths represent accumulated inclusive time, not wall-clock position.`}</span>
      }
    >
      {mode === "flame" ? (
        <div className="chart-wrap">
          <Chart
            id="flame-chart"
            aria-label="Call tree flame graph"
            spec={{ type: "flame", data: rows }}
          />
        </div>
      ) : (
        <DataTable
          key={revision}
          id="call-tree"
          rows={shown}
          columns={columns}
          onRow={(row) => inspectObject(row.name, row)}
        />
      )}
    </Card>
  );
}
