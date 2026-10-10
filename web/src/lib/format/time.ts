import { num } from "./numbers";
export const duration = (v: number | null | undefined) =>
  v == null
    ? "—"
    : v === 0
      ? "0 s"
      : Math.abs(v) < 1e-6
        ? `${num(v * 1e9, 2)} ns`
        : Math.abs(v) < 0.001
          ? `${num(v * 1e6, 2)} µs`
          : Math.abs(v) < 1
            ? `${num(v * 1000, 3)} ms`
            : `${num(v, 4)} s`;
