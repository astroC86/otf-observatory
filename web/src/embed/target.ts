import { Children, createContext, isValidElement, type ReactNode } from "react";

const parameters = new URLSearchParams(location.search);
export const embedTarget = parameters.get("embed") === "1" ? parameters.get("chart") || "" : "";
export const EmbeddedCardContext = createContext(false);
const targets = new Set<symbol>();
const listeners = new Set<() => void>();

export const hasEmbedTarget = () => targets.size > 0;

export function subscribeEmbed(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function registerEmbedTarget(): () => void {
  const token = Symbol();
  targets.add(token);
  if (targets.size === 1) listeners.forEach((listener) => listener());
  return () => {
    if (targets.delete(token) && targets.size === 0) {
      listeners.forEach((listener) => listener());
    }
  };
}

// Inspect React children, not DOM; custom charts expose their target id to Card/ChartGroup.
export function containsEmbedTarget(children: ReactNode): boolean {
  if (!embedTarget) return false;
  let found = false;
  Children.forEach(children, (child) => {
    if (!found && isValidElement<{ id?: string; children?: ReactNode }>(child))
      found = child.props.id === embedTarget || containsEmbedTarget(child.props.children);
  });
  return found;
}
