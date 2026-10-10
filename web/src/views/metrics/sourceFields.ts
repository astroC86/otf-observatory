import type { MetricDefinition } from "../../api/types/common";
import type { Option } from "../../components/controls/types";
import {
  ATTRIBUTE_REDUCTIONS,
  COUNTER_MODES,
  DIRECTIONS,
  ENDPOINTS,
  OPERATION_REDUCTIONS,
  SOURCE_TYPES,
  STORAGE_OPTIONS,
} from "./constants";

export interface SourceField {
  key: string;
  label: string;
  fallback: string;
  options?: readonly Option[];
  placeholder?: string;
  title?: string;
  list?: string;
}
const text = (label: string, placeholder: string) => ({ label, placeholder, fallback: "" });
const select = (label: string, options: readonly Option[], fallback: string) => ({
  label,
  options,
  fallback,
});
const FIELDS: Record<string, Omit<SourceField, "key">> = {
  type: select("Source", SOURCE_TYPES, "counter"),
  metric: select("Counter", [], ""),
  mode: select("Transform", COUNTER_MODES, "value"),
  formula: select("Saved metric", [], ""),
  value: { label: "Value", fallback: "1" },
  region: text("Function contains", "All functions"),
  functionPattern: {
    ...text("Function patterns", "MPI_*;compute*"),
    title:
      "Case-sensitive patterns separated by semicolons. * matches any characters. Blank includes all functions.",
  },
  endpoint: select("Endpoint", ENDPOINTS, "enter"),
  direction: select("Direction", DIRECTIONS, "send"),
  operation: text("Operation contains", "All operations"),
  functionStorage: {
    ...select("Function record storage", STORAGE_OPTIONS, "native"),
    title:
      "Native: calling-context definitions select calling-context storage for the whole trace. Per location: allow ordinary instrumented stacks on locations without calling-context events.",
  },
  paradigm: text("I/O paradigm", "All I/O paradigms"),
  attribute: text("Attribute name or ID", "Choose a recorded attribute"),
  attributeReduction: select("Stack reduction", ATTRIBUTE_REDUCTIONS, "top"),
  operationReduction: select("Active operation reduction", OPERATION_REDUCTIONS, "sum"),
};
export function sourceFields(
  type: string,
  metrics: readonly MetricDefinition[],
  library: readonly string[],
): SourceField[] {
  const keys =
    type === "counter"
      ? ["metric", "mode"]
      : type === "constant"
        ? ["value"]
        : type === "custom"
          ? ["formula"]
          : type.startsWith("function")
            ? [
                "region",
                "functionPattern",
                ...(type === "function_count" ? ["endpoint"] : []),
                "functionStorage",
              ]
            : type.startsWith("message")
              ? ["direction"]
              : ["operation"];
  if (type.startsWith("io_")) keys.push("paradigm");
  if (type.includes("attribute")) keys.push("attribute");
  if (type.startsWith("function_attribute")) keys.push("attributeReduction");
  if (["io_attribute", "io_bandwidth", "io_size"].includes(type)) keys.push("operationReduction");
  return ["type", ...keys].map((key) => ({
    key,
    ...FIELDS[key]!,
    ...(key === "metric"
      ? {
          options: metrics.map((metric) => [metric.id, `${metric.name} [${metric.unit}]`] as const),
        }
      : {}),
    ...(key === "formula" ? { options: [["", "Choose a metric"] as const, ...library] } : {}),
    ...(key === "attribute"
      ? {
          list: type.startsWith("function")
            ? "metric-function-attributes"
            : "metric-operation-attributes",
        }
      : {}),
  }));
}
export function selectValue(value: unknown, options: readonly Option[]): string {
  const text = String(value);
  const option =
    options.find((item) => String(typeof item === "object" ? item[0] : item) === text) ??
    options[0];
  return option === undefined ? "" : String(typeof option === "object" ? option[0] : option);
}
