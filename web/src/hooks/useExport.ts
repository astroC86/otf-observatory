import { useLayoutEffect } from "react";
import { setExport } from "../state/exports";
export function useExport<Row extends object>(rows: readonly Row[], name: string, enabled = true) {
  useLayoutEffect(() => {
    if (enabled) setExport(rows, name);
  }, [rows, name, enabled]);
}
