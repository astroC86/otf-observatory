import type { JsonObject, TraceMeta } from "../../api/types/common";
import {
  HIERARCHIES,
  REDUCTIONS,
  SOURCE_BASE_FIELDS,
  SOURCE_FIELDS,
  TIME_REDUCTIONS,
  VARIABLE_PATTERN,
} from "./constants";
import { selectValue, sourceFields } from "./sourceFields";
import type { MetricDraft, MetricLibrary, MetricProgram, MetricSource } from "./types";

export function defaultProgram(meta: TraceMeta): MetricProgram {
  const counter = meta.metrics[0];
  return {
    name: "Custom metric",
    unit: "",
    sources: {
      x: counter
        ? { type: "counter", metric: counter.id, mode: "value" }
        : { type: "function_active", region: "MPI" },
    },
    expression: "x",
    aggregation: "none",
    scope: "all",
    reduction: "none",
  };
}
export function readProgram(value: JsonObject | null, meta: TraceMeta): MetricProgram {
  // Session/library programs retain their exact JSON request fields.
  return value ? (value as MetricProgram) : defaultProgram(meta);
}
export function readLibrary(value: JsonObject | undefined): MetricLibrary {
  return (value || {}) as MetricLibrary;
}
export function createDraft(
  program: MetricProgram,
  meta: TraceMeta,
  library: readonly string[],
): MetricDraft {
  return {
    program: {
      ...program,
      name: String(program.name ?? ""),
      unit: String(program.unit || ""),
      expression: String(program.expression ?? ""),
      aggregation: selectValue(program.aggregation || "none", REDUCTIONS),
      scope: selectValue(program.scope || "all", HIERARCHIES),
      reduction: selectValue(program.reduction || "none", TIME_REDUCTIONS),
    },
    sources: Object.entries(program.sources).map(([variable, source]) => ({
      variable,
      source,
      fields: Object.fromEntries(
        sourceFields(source.type, meta.metrics, library).map((field) => {
          const value =
            field.key === "value"
              ? (source[field.key] ?? field.fallback)
              : source[field.key] || field.fallback;
          return [field.key, field.options ? selectValue(value, field.options) : String(value)];
        }),
      ),
      extra: JSON.stringify(
        Object.fromEntries(
          Object.entries(source).filter(([key]) => !SOURCE_BASE_FIELDS.includes(key)),
        ),
      ),
    })),
  };
}
export function captureProgram(draft: MetricDraft): MetricProgram {
  const sources: Record<string, MetricSource> = Object.create(null);
  for (const row of draft.sources) {
    const name = row.variable.trim();
    if (!VARIABLE_PATTERN.test(name) || Object.hasOwn(sources, name))
      throw Error("Each source needs a unique variable name.");
    const source: MetricSource = { ...row.source, type: row.fields.type ?? row.source.type };
    for (const key of SOURCE_FIELDS)
      if (row.fields[key] !== undefined) source[key] = row.fields[key];
    for (const key of ["functionPattern", "paradigm"]) if (source[key] === "") delete source[key];
    if (Object.hasOwn(row.fields, "value")) {
      source.value = Number(row.fields.value);
      if (!Number.isFinite(source.value)) throw Error("Enter a finite constant.");
    }
    const extra: unknown = JSON.parse(row.extra || "{}");
    if (!extra || Array.isArray(extra) || typeof extra !== "object")
      throw Error("Additional parameters must be a JSON object.");
    Object.assign(source, extra);
    sources[name] = source;
  }
  return { ...draft.program, name: draft.program.name.trim() || "Custom metric", sources };
}
