import type { HTMLAttributes } from "react";
import { containsEmbedTarget } from "../../embed/target";
import { useEmbedHidden } from "../../embed/useEmbedHidden";
export function ChartGroup({ children, ...props }: HTMLAttributes<HTMLDivElement>) {
  const hidden = useEmbedHidden(containsEmbedTarget(children));
  return (
    <div {...props} data-embed-hidden={hidden || undefined}>
      {children}
    </div>
  );
}
