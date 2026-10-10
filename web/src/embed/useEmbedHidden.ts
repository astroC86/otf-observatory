import { useContext, useSyncExternalStore } from "react";
import { EmbeddedCardContext, hasEmbedTarget, subscribeEmbed } from "./target";

export function useEmbedHidden(containsTarget = false): boolean {
  const inside = useContext(EmbeddedCardContext);
  const active = useSyncExternalStore(subscribeEmbed, hasEmbedTarget, hasEmbedTarget);
  return active && !inside && !containsTarget;
}
