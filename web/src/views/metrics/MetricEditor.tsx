import { useRef, useState } from "react";
import type { TraceMeta } from "../../api/types/common";
import { Card } from "../../components/panel/Card";
import { ControlBar } from "../../components/controls/ControlBar";
import { buttonControl, selectControl, textControl } from "../../components/controls/factories";
import { notify } from "../../state/uiActions";
import { HIERARCHIES, OPERATION_OPTIONS, REDUCTIONS, TIME_REDUCTIONS } from "./constants";
import { MetricSourceRow } from "./MetricSourceRow";
import { MetricPresetSelect } from "./MetricPresetSelect";
import { deleteMetric, exportLibrary, importLibrary, loadMetric, saveMetric } from "./library";
import { errorMessage } from "./requests";
import type { MetricEditorState } from "./useMetricEditor";
import type { StudioData } from "./types";

interface Props {
  editor: MetricEditorState;
  data: StudioData;
  meta: TraceMeta;
  library: readonly string[];
}
export function MetricEditor({ editor, data, meta, library }: Props) {
  const [saved, setSaved] = useState("");
  const file = useRef<HTMLInputElement>(null);
  const { draft, field } = editor;
  const program = draft.program;
  return (
    <Card
      title="Metric studio"
      caption={
        <span>
          Arithmetic preserves missing values as gaps. Comparisons and logic return true/false
          values; cumulative sums skip gaps and preserve history across zoom. Evaluation precedes
          display reduction.
        </span>
      }
    >
      <ControlBar
        controls={[
          textControl("metric-name", "Name", program.name, (value) => field("name", value)),
          textControl(
            "metric-unit",
            "Unit override",
            program.unit,
            (value) => field("unit", value),
            { placeholder: "Infer units" },
          ),
          {
            kind: "content",
            key: "preset",
            children: (
              <MetricPresetSelect
                presets={data.presets}
                onChange={(value) => editor.preset(value, data.presets)}
              />
            ),
          },
        ]}
      />
      {data.presetError ? (
        <p className="analysis-warning">{`Preset catalog: ${data.presetError}`}</p>
      ) : null}
      <div id="metric-sources">
        {draft.sources.map((row, index) => (
          <MetricSourceRow
            key={index}
            row={row}
            index={index}
            metrics={meta.metrics}
            library={library}
            onChange={(key, value) => editor.source(index, key, value)}
            onRemove={() => editor.remove(index)}
          />
        ))}
      </div>
      <ControlBar
        controls={[
          buttonControl("metric-add-source", "＋ Add source", editor.add),
          selectControl("metric-operation", "Insert operation", "", OPERATION_OPTIONS, (value) => {
            if (value) field("expression", value);
          }),
        ]}
      />
      <label className="expression-label">
        Expression
        <textarea
          id="metric-expression"
          aria-label="Custom metric expression"
          spellCheck={false}
          value={editor.expression}
          onChange={(event) => field("expression", event.currentTarget.value)}
        />
      </label>
      <ControlBar
        controls={[
          selectControl(
            "metric-aggregation",
            "Location reduction",
            program.aggregation,
            REDUCTIONS,
            (value) => field("aggregation", value),
          ),
          selectControl("metric-scope", "Hierarchy", program.scope, HIERARCHIES, (value) =>
            field("scope", value),
          ),
          selectControl(
            "metric-reduction",
            "Time reduction",
            program.reduction,
            TIME_REDUCTIONS,
            (value) => field("reduction", value),
          ),
          buttonControl("metric-evaluate", "Evaluate", () => editor.commit(), {
            className: "primary",
          }),
          buttonControl("metric-save", "Save metric", () => {
            try {
              saveMetric(editor.capture());
            } catch (error) {
              notify(errorMessage(error));
            }
          }),
        ]}
      />
      <ControlBar
        controls={[
          selectControl(
            "metric-saved",
            "Saved metrics",
            saved,
            [["", "Select metric"], ...library],
            setSaved,
          ),
          buttonControl("metric-load", "Load", () => loadMetric(saved)),
          buttonControl("metric-delete", "Delete", () => deleteMetric(saved)),
          buttonControl("metric-export", "Export library", exportLibrary),
          buttonControl("metric-import", "Import library", () => file.current?.click()),
          {
            kind: "content",
            key: "file",
            children: (
              <input
                ref={file}
                id="metric-file"
                type="file"
                accept=".json"
                hidden
                onChange={async (event) => {
                  const selected = event.currentTarget.files?.[0];
                  if (selected)
                    try {
                      await importLibrary(selected);
                    } catch (error) {
                      notify(errorMessage(error));
                    }
                }}
              />
            ),
          },
        ]}
      />
    </Card>
  );
}
