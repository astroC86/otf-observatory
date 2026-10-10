import type { ReactNode } from "react";
import type {
  ButtonControl,
  CheckboxControl,
  ControlBase,
  Option,
  SelectControl,
  TextControl,
} from "./types";
const EMPTY = Object.freeze({});
export function selectControl(
  id: string,
  label: ReactNode,
  value: string | number | null,
  options: readonly Option[],
  onChange: SelectControl["onChange"],
  extra: ControlBase = EMPTY,
): SelectControl {
  return { kind: "select", id, label, value, options, onChange, ...extra };
}
export function numberControl(
  id: string,
  label: ReactNode,
  value: string | number,
  onChange: TextControl["onChange"],
  extra: Omit<TextControl, "kind" | "value" | "onChange"> = EMPTY,
): TextControl {
  return { kind: "number", id, label, value, onChange, ...extra };
}
export function textControl(
  id: string,
  label: ReactNode,
  value: string | number,
  onChange: TextControl["onChange"],
  extra: Omit<TextControl, "kind" | "value" | "onChange"> = EMPTY,
): TextControl {
  return { kind: "text", id, label, value, onChange, ...extra };
}
export function checkboxControl(
  id: string,
  label: ReactNode,
  checked: boolean,
  onChange: CheckboxControl["onChange"],
  extra: ControlBase = EMPTY,
): CheckboxControl {
  return { kind: "checkbox", id, label, checked, onChange, ...extra };
}
export function buttonControl(
  id: string,
  children: ReactNode,
  onClick: ButtonControl["onClick"],
  extra: Omit<ButtonControl, "kind" | "children" | "onClick"> = EMPTY,
): ButtonControl {
  return { kind: "button", id, children, onClick, ...extra };
}
