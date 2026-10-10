import { hashKey } from "@tanstack/react-query";
import { useViewState } from "../../hooks/useViewState";
import { MetricStudioFrame } from "./MetricStudioFrame";
import { readProgram } from "./program";

export function MetricStudio() {
  const snapshot = useViewState();
  const program = readProgram(snapshot.metricProgram, snapshot.meta);
  return <MetricStudioFrame key={hashKey([program])} snapshot={snapshot} />;
}
