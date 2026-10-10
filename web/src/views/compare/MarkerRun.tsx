import { useMutation, useQuery } from "@tanstack/react-query";
import { queryKeys } from "../../api/queryKeys";
import { queryFn } from "../../api/queryFn";
import { OptionList } from "../../components/controls/OptionList";
import { duration } from "../../lib/format/time";
import { getState } from "../../state/store";
import { useStore } from "../../state/useStore";
import { scheduleRender } from "../../state/viewActions";
import { notify } from "../../state/uiActions";
import { captureMarkerInputs, EMPTY_MARKER_INPUT, setMarkerInput } from "./actions";
import { openRuns } from "./requests";
import type { MarkerOptions } from "./types";

const FIELDS = [
  ["time", "Recorded marker (s)"],
  ["offset", "Display offset (s)"],
] as const;

export function MarkerRun({ id, name, index }: { id: string; name: string; index: number }) {
  const input = useStore((state) => state.markerInputs[id] || EMPTY_MARKER_INPUT);
  const options = useQuery({
    queryKey: queryKeys.request("marker-options", { id }),
    queryFn: queryFn<MarkerOptions>,
    enabled: false,
  });
  const recorded = options.data;
  const load = useMutation({
    mutationFn: async () => {
      captureMarkerInputs();
      await openRuns([id]);
      await options.refetch({ throwOnError: true });
    },
    onError: (error: Error) => notify(error.message),
  });
  return (
    <div className="marker-run" data-marker-row={id}>
      <strong title={name}>{`${index ? `Run ${index}` : "Baseline"} · ${name || id}`}</strong>
      {FIELDS.map(([field, label]) => (
        <label key={field}>
          {label}
          <input
            type="number"
            step="any"
            data-marker-field={field}
            value={input[field]}
            onChange={(event) => {
              captureMarkerInputs();
              const value = { ...getState().markerInputs[id]!, [field]: event.target.value };
              if (field === "time") delete value.marker;
              setMarkerInput(id, value);
            }}
          />
        </label>
      ))}
      <button
        data-load-markers={id}
        disabled={load.isPending}
        onClick={() => load.mutate(undefined, { onSuccess: scheduleRender })}
      >
        Recorded markers
      </button>
      {recorded && (
        <label className="marker-catalog">
          Marker{" "}
          <select
            data-marker-select={id}
            value={input.marker == null ? "" : String(input.marker)}
            onChange={(event) => {
              const item = recorded.markers.find(
                (marker) => String(marker.id) === event.target.value,
              );
              captureMarkerInputs();
              const value = { ...getState().markerInputs[id]! };
              if (item) Object.assign(value, { marker: item.id, time: item.time });
              else delete value.marker;
              setMarkerInput(id, value);
              scheduleRender();
            }}
          >
            <OptionList
              items={[
                ["", "Choose a recorded marker"],
                ...recorded.markers.map(
                  (marker) => [marker.id, `${marker.name} · ${duration(marker.time)}`] as const,
                ),
              ]}
            />
          </select>
          <small>{`${recorded.markers.length} of ${recorded.total} markers${recorded.truncated ? "; enter a timestamp for markers beyond this list" : ""}`}</small>
        </label>
      )}
    </div>
  );
}
