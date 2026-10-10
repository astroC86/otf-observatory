import { Fragment, type ReactNode } from "react";
export interface KeyValueItem {
  label: ReactNode;
  value: ReactNode;
}
export function KeyValueList({
  items,
  className = "properties",
}: {
  items: readonly KeyValueItem[];
  className?: string | null;
}) {
  const fields = items.map((item, index) => (
    <div key={index} className="context-field">
      <span>{item.label}</span>
      <span>{item.value}</span>
    </div>
  ));
  return className === null ? (
    <Fragment>{fields}</Fragment>
  ) : (
    <div className={className}>{fields}</div>
  );
}
