import type { ReactNode } from "react";
import { useEmbedHidden } from "../../embed/useEmbedHidden";
export interface StatItem<Value extends ReactNode = ReactNode> {
  id?: string;
  label: ReactNode;
  value: Value;
  detail?: ReactNode;
  truncateDetail?: boolean;
  format?: (value: Value) => ReactNode;
}
export function StatGrid<Value extends ReactNode>({
  items,
  details = true,
  variant = "metrics",
}: {
  items: readonly StatItem<Value>[];
  details?: boolean;
  variant?: "metrics" | "facts";
}) {
  const hidden = useEmbedHidden();
  return (
    <div
      className={variant === "facts" ? "trace-facts" : "metric-strip"}
      data-embed-hidden={hidden || undefined}
    >
      {items.map((item, index) => {
        const value = item.format ? item.format(item.value) : item.value;
        return variant === "facts" ? (
          <div key={index}>
            <span id={item.id}>{value}</span>
            <small>{item.label}</small>
          </div>
        ) : (
          <div key={index} className="stat-box">
            <label>{item.label}</label>
            <strong>{value}</strong>
            {details ? (
              <small
                className={item.truncateDetail ? "stat-detail-ellipsis" : undefined}
                title={
                  item.truncateDetail && typeof item.detail === "string" ? item.detail : undefined
                }
              >
                {item.detail ?? ""}
              </small>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
