import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { getState } from "../../state/store";
import { setExport } from "../../state/exports";
import { EmptyState } from "../ui/EmptyState";
import { cellValue, sortedRows, tableRows } from "./sorting";
import type { ColumnDef } from "./types";
export interface DataTableProps<Row extends object> {
  id?: string;
  rows: readonly Row[];
  columns: readonly ColumnDef<Row>[];
  maxHeight?: number;
  onRow?: (row: Row) => void;
  onContextMenu?: (event: MouseEvent<HTMLTableRowElement>, row: Row) => void;
  selectedRegion?: string | null | (() => string | null);
  exportName?: string;
}
export function DataTable<Row extends object>({
  id,
  rows,
  columns,
  onRow,
  onContextMenu,
  maxHeight = 590,
  selectedRegion = getState().selectedRegion,
  exportName = "",
}: DataTableProps<Row>) {
  const [order, setOrder] = useState({ key: "", direction: -1 });
  const data = useMemo(() => sortedRows(rows, columns, order), [rows, columns, order]);
  useEffect(() => {
    if (exportName) setExport(tableRows(data, columns), exportName);
  }, [data, columns, exportName]);
  const selected = typeof selectedRegion === "function" ? selectedRegion() : selectedRegion;
  const content = (
    <div className="table-wrap" style={{ maxHeight }}>
      <table>
        <thead>
          <tr>
            {columns.map((column, index) => (
              <th
                key={index}
                data-sort={column.key}
                className={column.number || column.numeric ? "number" : ""}
                onClick={() =>
                  setOrder((previous) => ({
                    key: String(column.key),
                    direction: previous.key === column.key ? -previous.direction : -1,
                  }))
                }
              >{`${column.label}${order.key === column.key ? (order.direction < 0 ? " ↓" : " ↑") : ""}`}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, index) => (
            <tr
              key={index}
              data-index={index}
              className={selected && cellValue(row, "region") === selected ? "selected" : ""}
              onClick={() => onRow?.(row)}
              onContextMenu={onContextMenu ? (event) => onContextMenu(event, row) : undefined}
            >
              {columns.map((column, columnIndex) => {
                const value = cellValue(row, column.key);
                return (
                  <td
                    key={columnIndex}
                    className={
                      typeof column.className === "function"
                        ? column.className(row)
                        : (column.className ??
                          (column.number || column.numeric ? "number" : "name-cell"))
                    }
                    title={column.tooltip ? column.tooltip(value, row) : String(value ?? "")}
                  >
                    {column.render
                      ? column.render(value, row)
                      : column.format
                        ? column.format(value)
                        : String(value ?? "—")}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {data.length ? null : (
        <EmptyState
          title="No data in this selection"
          detail="Widen the time range or change the filters."
        />
      )}
    </div>
  );
  return id ? <div id={id}>{content}</div> : content;
}
