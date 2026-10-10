import { Fragment, isValidElement, type ReactNode } from "react";
import { ControlBar } from "../../components/controls/ControlBar";
import type { ControlSpec } from "../../components/controls/types";

export interface DetailSpec {
  heading: string;
  body: ReactNode[];
  actions?: ControlSpec[];
  children?: ReactNode;
}
export function EvidenceDetail({ heading, body, actions, children }: DetailSpec) {
  return (
    <>
      <h3>{heading}</h3>
      {body.map((item, index) => (
        <Fragment key={index}>
          {item == null || item === false ? null : isValidElement(item) ? item : <p>{item}</p>}
        </Fragment>
      ))}
      {actions && <ControlBar className="context-actions" controls={actions} />}
      {children}
    </>
  );
}
