import { useEffect } from "react";
import { useEmbed } from "./embed/useEmbed";
import { boot } from "./state/trace/boot";
import { getUi, updateUi } from "./state/store";
import { useUi } from "./state/useUi";
import { initializeMetricLibrary } from "./views/metrics/library";
export default function Bootstrap() {
  const initialized = useUi((value) => value.initialized);
  useEmbed(initialized);
  useEffect(() => {
    initializeMetricLibrary();
    updateUi({ initialized: true });
    if (!getUi().embedded) void boot();
  }, []);
  return null;
}
