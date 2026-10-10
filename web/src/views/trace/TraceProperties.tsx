import { useMemo } from "react";
import { duration } from "../../lib/format/time";
import { num } from "../../lib/format/numbers";
import { KeyValueList } from "../../components/ui/KeyValueList";
import type { TraceMeta } from "../../api/types/common";

export function TraceProperties({ meta }: { meta: TraceMeta }) {
  const items = useMemo(
    () =>
      Object.entries({
        Archive: meta.path,
        Format: meta.format,
        Duration: duration(meta.duration),
        "Timer resolution": `${meta.clock.resolution} ticks/s`,
        "Global clock offset": meta.clock.offset,
        Events: num(meta.counts.events, 0),
        "Indexed call segments": num(meta.counts.spans, 0),
        "MPI messages": num(meta.counts.messages, 0),
        "Counter samples": num(meta.counts.metrics, 0),
        "Calling-context samples": num(meta.counts.samples, 0),
        Locations: meta.locations.length,
        "Region definitions": meta.regions.length,
        "Indexing time": `${meta.importSeconds} s`,
        Decoder: "Official OTF2 library / local OTF reader",
      }).map(([label, value]) => ({ label, value: `${value ?? ""}` })),
    [meta],
  );
  return <KeyValueList items={items} />;
}
