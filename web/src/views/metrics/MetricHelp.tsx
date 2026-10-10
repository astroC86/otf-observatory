import { useMutation } from "@tanstack/react-query";
import { Card } from "../../components/panel/Card";
import { api } from "../../api/client";
import { inspectObject } from "../../state/inspection";
import { notify } from "../../state/uiActions";
import { OPERATIONS } from "./constants";
import { errorMessage } from "./requests";

export function MetricHelp() {
  const capabilities = useMutation({
    mutationKey: ["metric-capabilities"],
    mutationFn: () => api("metric/capabilities"),
    onSuccess: (data) => inspectObject("Metric engine capabilities", data),
    onError: (error) => notify(errorMessage(error)),
  });
  return (
    <Card title="Operations & source reference">
      <details className="metric-help">
        <summary>Supported operations and interpretation</summary>
        <p>
          Arithmetic, comparisons, positive-value logical operations, NaN detection/replacement,
          min/max combination, limits, interpolation, logarithms, difference, differentiation,
          integration, cumulative sum and hierarchy aggregation are available.
        </p>
        <pre className="code-block">{OPERATIONS.join("\n")}</pre>
        <p>
          Temporal reductions operate on evaluated streams. Integration and cumulative counts
          preserve history through zoom. Location reductions combine interval-weighted values over a
          shared time grid.
        </p>
        <p>
          I/O count is cumulative; message count measures concurrent transfers. I/O size, bandwidth
          and attributes reduce active operations and have gaps while idle. Message transfer time is
          a pulse one trace tick long at the transfer start. Missing operation endpoints appear in
          the source notes.
        </p>
        <button id="metric-capabilities" onClick={() => capabilities.mutate()}>
          Inspect engine capabilities
        </button>
      </details>
    </Card>
  );
}
