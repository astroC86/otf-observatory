import type { ReactNode } from "react";
export interface ColumnDef<Row> {
  key: keyof Row | (string & {});
  label: string;
  number?: boolean;
  numeric?: boolean;
  render?: (value: unknown, row: Row) => ReactNode;
  format?: (value: unknown) => ReactNode;
  sort?: (a: Row, b: Row) => number;
  tooltip?: (value: unknown, row: Row) => string;
  className?: string | ((row: Row) => string);
}
