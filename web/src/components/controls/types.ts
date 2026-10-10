import type { ReactNode, KeyboardEventHandler, MouseEventHandler, CSSProperties } from "react";
export type Option = string | number | readonly [string | number, ReactNode];
export interface ControlBase {
  id?: string;
  label?: ReactNode;
  suffix?: ReactNode;
  labelAfter?: boolean;
  labelClassName?: string;
  className?: string;
  ariaLabel?: string;
  ariaPressed?: boolean;
  title?: string;
  disabled?: boolean;
  data?: Record<string, string | number>;
}
export interface TextControl extends ControlBase {
  kind: "number" | "search" | "text" | "color";
  value: string | number;
  onChange?: (value: string) => void;
  event?: "input" | "change";
  min?: string | number;
  max?: string | number;
  step?: string | number;
  size?: number;
  placeholder?: string;
  list?: string;
  onKeyDown?: KeyboardEventHandler<HTMLInputElement>;
}
export interface SelectControl extends ControlBase {
  kind: "select";
  value: string | number | null;
  options: readonly Option[];
  onChange: (value: string) => void;
}
export interface CheckboxControl extends ControlBase {
  kind: "checkbox";
  checked: boolean;
  onChange: (value: boolean) => void;
}
export interface ButtonControl extends ControlBase {
  kind: "button";
  children: ReactNode;
  onClick?: MouseEventHandler<HTMLButtonElement>;
  type?: "button" | "submit" | "reset";
}
interface ContentControl {
  kind: "content";
  children: ReactNode;
  key?: string;
}
export type ControlSpec =
  TextControl | SelectControl | CheckboxControl | ButtonControl | ContentControl;
export interface ControlBarProps {
  controls: readonly ControlSpec[];
  className?: string | null;
  id?: string;
  style?: CSSProperties;
}
