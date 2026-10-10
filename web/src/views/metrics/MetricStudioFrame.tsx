import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card } from "../../components/panel/Card";
import { queryKeys } from "../../api/queryKeys";
import { queryClient } from "../../api/queryClient";
import { useEmbedHidden } from "../../embed/useEmbedHidden";
import { updateState } from "../../state/store";
import { finishRender, scheduleRender } from "../../state/viewActions";
import type { ViewState } from "../../state/types";
import { readLibrary, readProgram } from "./program";
import { loadStudio } from "./requests";
import { useMetricEditor } from "./useMetricEditor";
import { useMetricGrid } from "./useMetricGrid";
import { MetricEditor } from "./MetricEditor";
import { MetricResults } from "./MetricResults";
import { MetricHelp } from "./MetricHelp";

export function MetricStudioFrame({ snapshot }: { snapshot: ViewState }) {
  const [program] = useState(() => readProgram(snapshot.metricProgram, snapshot.meta));
  const started = useMemo(() => performance.now(), [snapshot.epoch]);
  const library = Object.keys(readLibrary(snapshot.metricLibrary));
  const editor = useMetricEditor(program, snapshot.meta, library);
  const { grid, canvasRef } = useMetricGrid(snapshot.metricStepSize, "line", () => {
    try {
      editor.capture();
      scheduleRender();
    } catch {
      /* Keep invalid unsaved edits. */
    }
  });
  const queryKey = [
    ...queryKeys.view({ ...snapshot, metricProgram: program }),
    "metric-studio",
    program,
    grid?.bins,
    grid?.queryable,
  ];
  const response = useQuery({
    queryKey,
    enabled: !!grid,
    queryFn: ({ signal }) => loadStudio(program, grid!, snapshot, signal),
  });
  const hidden = useEmbedHidden() || undefined;
  useLayoutEffect(() => {
    if (!snapshot.metricProgram) updateState({ metricProgram: program });
  }, [snapshot.epoch]);
  const settled = !response.isPending && !response.isFetching;
  useLayoutEffect(() => {
    if (settled) finishRender(snapshot.epoch, started, response.error);
  }, [settled, response.error?.message, snapshot.epoch, started]);
  const displayed = useRef(false);
  if (response.data) displayed.current = true;
  if (grid && response.isPending && displayed.current)
    throw queryClient.fetchQuery({
      queryKey,
      queryFn: ({ signal }) => loadStudio(program, grid, snapshot, signal),
    });
  if (response.error)
    return (
      <div className="analysis-warning" role="alert">
        {response.error.message}
      </div>
    );
  const data = response.data;
  if (!data || !grid)
    return (
      <Card title={program.name}>
        <div className="chart-wrap">
          <canvas
            ref={canvasRef}
            id="studio-chart"
            className="chart"
            aria-label="Custom metric result timeline"
          />
        </div>
      </Card>
    );
  return (
    <>
      {["function", "operation"].map((kind) => (
        <datalist key={kind} id={`metric-${kind}-attributes`} data-embed-hidden={hidden}>
          {data.attributes
            .filter((attribute) => kind === "function" || attribute.kind === "attribute")
            .map((attribute) => (
              <option
                key={`${attribute.kind}:${attribute.id}`}
                value={attribute.id}
                label={`${attribute.name} · ${attribute.kind}`}
              >{`${attribute.name} · ${attribute.kind}`}</option>
            ))}
        </datalist>
      ))}
      {data.attributeError ? (
        <p
          className="analysis-warning"
          data-embed-hidden={hidden}
        >{`Attribute catalog: ${data.attributeError}`}</p>
      ) : null}
      <MetricEditor editor={editor} data={data} meta={snapshot.meta} library={library} />
      {data.evaluation.status === "error" ? (
        <div className="analysis-warning" role="alert" data-embed-hidden={hidden}>
          {data.evaluation.message}
        </div>
      ) : (
        <MetricResults
          result={data.evaluation.result}
          program={program}
          snapshot={snapshot}
          grid={grid}
          canvasRef={canvasRef}
          capture={editor.capture}
        />
      )}
      <MetricHelp />
    </>
  );
}
