import type { ColumnDef } from "./types";
export interface TableOrder {
  key: string;
  direction: number;
}
export function cellValue<Row extends object>(row: Row, key: keyof Row | string): unknown {
  return Reflect.get(row, key);
}
export function sortedRows<Row extends object>(
  rows: readonly Row[],
  columns: readonly ColumnDef<Row>[],
  order: TableOrder,
): readonly Row[] {
  if (!order.key) return rows;
  const column = columns.find((candidate) => candidate.key === order.key);
  return rows.toSorted((a, b) => {
    if (column?.sort) return column.sort(a, b) * order.direction;
    const x = cellValue(a, order.key),
      y = cellValue(b, order.key);
    return (
      (typeof x === "number" && typeof y === "number"
        ? x - y
        : String(x ?? "").localeCompare(String(y ?? ""))) * order.direction
    );
  });
}
export function tableRows<Row extends object>(
  rows: readonly Row[],
  columns: readonly ColumnDef<Row>[],
) {
  return rows.map((row) =>
    Object.fromEntries(columns.map((column) => [column.key, cellValue(row, column.key)])),
  );
}
