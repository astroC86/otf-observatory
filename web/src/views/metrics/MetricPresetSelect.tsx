import { OptionList } from "../../components/controls/OptionList";
import { PRESETS } from "./constants";
import type { MetricPreset } from "./types";

export function MetricPresetSelect({
  presets,
  onChange,
}: {
  presets: readonly MetricPreset[];
  onChange: (value: string) => void;
}) {
  return (
    <label>
      Preset{" "}
      <select
        id="metric-preset"
        defaultValue=""
        onChange={(event) => onChange(event.currentTarget.value)}
      >
        <OptionList items={PRESETS} />
        {presets.length ? (
          <optgroup label="Built-in metrics">
            {presets.map((preset) => (
              <option
                key={preset.id}
                value={`native:${preset.id}`}
                disabled={!preset.available}
                title={preset.reason || preset.name}
              >
                {`${preset.name}${preset.available ? "" : ` — ${preset.reason || "Required recording is unavailable"}`}`}
              </option>
            ))}
          </optgroup>
        ) : null}
      </select>
    </label>
  );
}
