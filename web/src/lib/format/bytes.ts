import { num } from "./numbers";
export const bytes = (v: number | null | undefined) =>
  v == null
    ? "—"
    : Math.abs(v) >= 1e9
      ? `${num(v / 1e9)} GB`
      : Math.abs(v) >= 1e6
        ? `${num(v / 1e6)} MB`
        : Math.abs(v) >= 1e3
          ? `${num(v / 1e3)} kB`
          : `${num(v, 0)} B`;
