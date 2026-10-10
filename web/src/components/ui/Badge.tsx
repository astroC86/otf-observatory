import type { HTMLAttributes } from "react";
export function Badge({ className = "badge", ...props }: HTMLAttributes<HTMLSpanElement>) {
  return <span className={className} {...props} />;
}
