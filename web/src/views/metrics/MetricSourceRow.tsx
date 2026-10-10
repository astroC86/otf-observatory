import type { MetricDefinition } from "../../api/types/common";
import { ControlBar } from "../../components/controls/ControlBar";
import { sourceFields } from "./sourceFields";
import type { SourceDraft } from "./types";

interface Props {
  row: SourceDraft;
  index: number;
  metrics: readonly MetricDefinition[];
  library: readonly string[];
  onChange: (field: string, value: string) => void;
  onRemove: () => void;
}
export function MetricSourceRow({ row, index, metrics, library, onChange, onRemove }: Props) {
  return (
    <div className="metric-source" data-source-row={index}>
      <div className="source-symbol">
        <input
          data-field="variable"
          aria-label={`Source variable ${index + 1}`}
          defaultValue={row.variable}
          maxLength={32}
          onChange={(event) => onChange("variable", event.currentTarget.value)}
        />
      </div>
      <div className="source-fields">
        <ControlBar
          className={null}
          controls={sourceFields(row.source.type, metrics, library).map(
            ({ key, options, fallback, ...props }) => ({
              ...props,
              data: { field: key },
              value: row.fields[key] ?? fallback,
              ariaLabel: key === "type" ? `Source type ${index + 1}` : undefined,
              onChange: (value: string) => onChange(key, value),
              ...(options
                ? { kind: "select" as const, options }
                : {
                    kind: key === "value" ? ("number" as const) : ("text" as const),
                    step: key === "value" ? "any" : undefined,
                  }),
            }),
          )}
        />
        <details>
          <summary>Additional source parameters</summary>
          <textarea
            data-field="extra"
            aria-label={`Additional parameters ${index + 1}`}
            spellCheck={false}
            defaultValue={row.extra}
            onChange={(event) => onChange("extra", event.currentTarget.value)}
          />
          <small className="muted">
            Optional filters: group, exclude, values, tag, comm, file, handle, unit. JSON object.
          </small>
        </details>
      </div>
      <button
        data-remove-source={index}
        aria-label={`Remove source ${index + 1}`}
        onClick={onRemove}
      >
        ×
      </button>
    </div>
  );
}
