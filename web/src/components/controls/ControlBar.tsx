import { Fragment } from "react";
import { Control } from "./Control";
import type { ControlBarProps } from "./types";
import { useEmbedHidden } from "../../embed/useEmbedHidden";
export function ControlBar({ controls, className = "filter-line", id, style }: ControlBarProps) {
  const hidden = useEmbedHidden();
  const children = controls.map((control, index) => (
    <Control
      key={control.kind === "content" ? (control.key ?? index) : (control.id ?? index)}
      control={control}
    />
  ));
  return className === null ? (
    <Fragment>{children}</Fragment>
  ) : (
    <div id={id} className={className} style={style} data-embed-hidden={hidden || undefined}>
      {children}
    </div>
  );
}
