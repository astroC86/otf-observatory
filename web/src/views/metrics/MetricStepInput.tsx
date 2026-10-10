import { metricStep } from "./metricGrid";

export function MetricStepInput({
  value,
  onChange,
}: {
  value: number;
  onChange: (value: number) => void;
}) {
  return (
    <label>
      Pixel step{" "}
      <input
        id="metric-step"
        type="number"
        min="1"
        max="4294967295"
        step="1"
        defaultValue={metricStep(value)}
        aria-label="Metric pixel step"
        title="Logical plot pixels per reduction cell"
        onChange={(event) => onChange(metricStep(event.currentTarget.value))}
      />
    </label>
  );
}
