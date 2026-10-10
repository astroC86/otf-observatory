import type { ControlSpec } from "../../components/controls/types";
import { buttonControl } from "../../components/controls/factories";
import { setRange } from "../../state/rangeActions";
import type { Operation } from "./types";

export function hasOperationRange(
  value: Operation | undefined,
): value is Operation & { start: number; end: number } {
  return (
    typeof value?.start === "number" &&
    Number.isFinite(value.start) &&
    typeof value.end === "number" &&
    Number.isFinite(value.end) &&
    value.end > value.start
  );
}
export function rangeAction(
  id: string,
  label: string,
  value: Operation | undefined,
  finiteEnd = true,
): ControlSpec {
  const start = value?.start,
    end = value?.end;
  const valid =
    typeof start === "number" &&
    Number.isFinite(start) &&
    typeof end === "number" &&
    (!finiteEnd || Number.isFinite(end)) &&
    end > start;
  return buttonControl(
    id,
    label,
    () => {
      if (valid) setRange(start, end);
    },
    { disabled: !valid },
  );
}
