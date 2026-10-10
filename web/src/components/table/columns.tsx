import type { ReactNode } from "react";
import { bytes } from "../../lib/format/bytes";
import { duration } from "../../lib/format/time";
import { num } from "../../lib/format/numbers";
import { color } from "../../state/selectors";
import type { ColumnDef } from "./types";
export const col = <Row extends object>(
  key: keyof Row | string,
  label: string,
  render?: (row: Row) => ReactNode,
): ColumnDef<Row> => ({ key, label, ...(render ? { render: (_, row) => render(row) } : {}) });
export const timeCol = <Row extends object>(
  key: keyof Row | string,
  label: string,
  number = true,
): ColumnDef<Row> => ({
  key,
  label,
  number,
  format: (value) => duration(typeof value === "number" ? value : null),
});
export const countCol = <Row extends object>(
  key: keyof Row | string,
  label: string,
  number = true,
): ColumnDef<Row> => ({
  key,
  label,
  number,
  format: (value) => num(value, 0),
});
export const bytesCol = <Row extends object>(
  key: keyof Row | string,
  label: string,
  number = true,
): ColumnDef<Row> => ({
  key,
  label,
  number,
  format: (value) => bytes(typeof value === "number" ? value : null),
});
export const nameCol = <Row extends object>(byGroup = false): ColumnDef<Row> => ({
  key: "name",
  label: "Function",
  render: (value, row) => (
    <>
      <i
        className="swatch"
        style={{
          background: color(
            String(("region" in row && row.region) || ("id" in row && row.id) || ""),
            byGroup,
          ),
        }}
      />
      {` \u00a0${value ?? ""}`}
    </>
  ),
});
