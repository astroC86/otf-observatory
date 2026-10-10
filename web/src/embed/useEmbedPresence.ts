import { useLayoutEffect } from "react";
import { registerEmbedTarget } from "./target";

export function useEmbedPresence(present: boolean): void {
  useLayoutEffect(() => {
    if (present) return registerEmbedTarget();
  }, [present]);
}
