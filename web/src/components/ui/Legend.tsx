import type { HTMLAttributes } from "react";
export interface LegendItem extends Omit<HTMLAttributes<HTMLSpanElement>, "color"> {
  label: string;
  color: string;
}
export function Legend({
  items,
  onClick,
  ...props
}: Omit<HTMLAttributes<HTMLDivElement>, "onClick"> & {
  items: readonly LegendItem[];
  onClick?: (label: string) => void;
}) {
  return (
    <div className="legend" {...props}>
      {items.map(({ label, color, ...item }, index) => (
        <span key={index} className="legend-item" {...item} onClick={() => onClick?.(label)}>
          <i className="swatch" style={{ background: color }} />
          {label}
        </span>
      ))}
    </div>
  );
}
