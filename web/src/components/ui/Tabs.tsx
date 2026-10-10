import type { HTMLAttributes, ReactNode } from "react";
export interface TabsProps extends Omit<HTMLAttributes<HTMLElement>, "className" | "onChange"> {
  as?: "div" | "nav";
  className?: string | null;
  dataKey?: string;
  items: readonly (readonly [string, ReactNode])[];
  value: string;
  onChange: (value: string) => void;
}
export function Tabs({
  as: Element = "div",
  className = "segmented",
  dataKey,
  items,
  value,
  onChange,
  ...props
}: TabsProps) {
  return (
    <Element className={className ?? undefined} {...props}>
      {items.map(([key, label]) => (
        <button
          key={key}
          {...(dataKey ? { ["data-" + dataKey]: key } : {})}
          className={key === value ? "active" : ""}
          onClick={() => onChange(key)}
        >
          {label}
        </button>
      ))}
    </Element>
  );
}
