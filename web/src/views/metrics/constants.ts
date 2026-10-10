import type { Option } from "../../components/controls/types";

export const SOURCE_TYPES: readonly Option[] = [
  ["counter", "Trace counter"],
  ["constant", "Constant value"],
  ["custom", "Saved custom metric"],
  ["function_active", "Function is active"],
  ["function_duration", "Function duration"],
  ["function_count", "Cumulative function count"],
  ["function_hits", "Cumulative function sampling hits"],
  ["function_attribute", "Function numeric attribute"],
  ["function_attribute_active", "Function attribute is active"],
  ["io_attribute", "I/O attribute"],
  ["io_bandwidth", "I/O bandwidth"],
  ["io_count", "Cumulative I/O operation count"],
  ["io_simultaneous", "I/O simultaneous operations"],
  ["io_size", "I/O transaction size"],
  ["message_rate", "Message data rate"],
  ["message_count", "Concurrent message count"],
  ["message_duration", "Message transfer time"],
  ["message_volume", "Message volume"],
  ["message_simultaneous", "Simultaneous messages"],
];
export const REDUCTIONS = [
  "none",
  "sum",
  "mean",
  "min",
  "max",
  "count",
  "median",
  "stddev",
  "variance",
  "first",
  "last",
  "p95",
];
export const TIME_REDUCTIONS = [...REDUCTIONS, "integral"];
export const OPERATIONS = [
  "x + y",
  "x - y",
  "x * y",
  "x / y",
  "logical_and(x, y)",
  "logical_or(x, y)",
  "logical_xor(x, y)",
  "logical_not(x)",
  "x < y",
  "x <= y",
  "x > y",
  "x >= y",
  "x == y",
  "x != y",
  "isnan(x)",
  "replace_nan(x, 0)",
  "combine_max(x, y)",
  "combine_min(x, y)",
  "lower_limit(x, 0)",
  "upper_limit(x, 1)",
  "differentiate(x)",
  "interpolate(x)",
  "log(x, 10)",
  "difference(x)",
  "integrate(x)",
  "cumsum(x)",
  "aggregate(x, 'sum', 'group')",
  "moving_mean(x, 0.1)",
  "moving_stddev(x, 0.1)",
  "where(x > 0, y, 0)",
  "sqrt(x)",
  "abs(x)",
];
export const OPERATION_OPTIONS: readonly Option[] = [["", "Choose operation"], ...OPERATIONS];
export const HIERARCHIES: readonly Option[] = [
  ["all", "All selected locations"],
  ["group", "Location group"],
  ["system", "System node"],
];
export const PRESETS: readonly Option[] = [
  ["", "Choose a starting point"],
  ["mpi", "MPI activity"],
  ["wait", "MPI Wait call duration"],
  ["io", "I/O bandwidth"],
  ["messages", "Sent message volume"],
  ["counter", "Recorded counter derivative"],
];
export const SOURCE_FIELDS = [
  "metric",
  "mode",
  "formula",
  "region",
  "functionPattern",
  "functionStorage",
  "paradigm",
  "endpoint",
  "direction",
  "operation",
  "attribute",
  "attributeReduction",
  "operationReduction",
];
export const SOURCE_BASE_FIELDS = ["type", "value", ...SOURCE_FIELDS];
export const VARIABLE_PATTERN = /^[a-zA-Z_][a-zA-Z0-9_]*$/;
export const COUNTER_MODES = ["value", "delta", "rate"];
export const ENDPOINTS = ["enter", "leave", "both"];
export const DIRECTIONS = ["send", "receive", "both"];
export const STORAGE_OPTIONS: readonly Option[] = [
  ["native", "Native trace-wide selection"],
  ["per-location", "Per location (extension)"],
];
export const ATTRIBUTE_REDUCTIONS: readonly Option[] = [
  ["top", "Current function"],
  ["bottom", "Outermost available"],
  ["sum", "Sum"],
  ["min", "Minimum"],
  ["max", "Maximum"],
  ["mean", "Mean"],
];
export const OPERATION_REDUCTIONS: readonly Option[] = [
  ["first", "First"],
  ["last", "Last"],
  ["sum", "Sum"],
  ["min", "Minimum"],
  ["max", "Maximum"],
  ["mean", "Mean"],
];
