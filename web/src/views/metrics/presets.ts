import type { TraceMeta } from "../../api/types/common";
import { defaultProgram } from "./program";
import type { MetricProgram } from "./types";

type StartingPreset = Pick<MetricProgram, "sources" | "expression" | "name" | "unit">;
const STARTING_PRESETS: Record<string, StartingPreset> = {
  mpi: {
    sources: { x: { type: "function_active", region: "MPI" } },
    expression: "x",
    name: "MPI activity",
    unit: "fraction",
  },
  wait: {
    sources: { x: { type: "function_duration", region: "MPI_Wait" } },
    expression: "x",
    name: "MPI Wait call duration",
    unit: "s",
  },
  io: {
    sources: { x: { type: "io_bandwidth" } },
    expression: "x",
    name: "I/O bandwidth",
    unit: "B/s",
  },
  messages: {
    sources: { x: { type: "message_volume", direction: "send" } },
    expression: "x",
    name: "Sent message volume",
    unit: "B",
  },
};
export function startingPreset(name: string, meta: TraceMeta): MetricProgram | undefined {
  if (name === "counter")
    return {
      ...defaultProgram(meta),
      sources: { x: { type: "counter", metric: meta.metrics[0]?.id || "", mode: "value" } },
      expression: "differentiate(x)",
      name: "Counter derivative",
      unit: "",
    };
  const preset = STARTING_PRESETS[name];
  return preset ? { ...defaultProgram(meta), ...preset } : undefined;
}
