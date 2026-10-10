import { createElement, Fragment, useMemo, type CSSProperties, type ReactNode } from "react";
// Existing chart tips contain trusted pre-escaped strong/br markup. Parse it in
// a detached document and render React nodes; never assign HTML to owned DOM.
export function TrustedMarkup({ html }: { html: string }) {
  const children = useMemo(() => {
    const document = new DOMParser().parseFromString(html, "text/html");
    function render(node: ChildNode, index: number): ReactNode {
      if (node.nodeType === Node.TEXT_NODE) return node.textContent;
      if (!(node instanceof HTMLElement)) return null;
      const props: Record<string, unknown> = { key: index };
      for (const { name, value } of node.attributes) {
        if (name.startsWith("on")) continue;
        if (name === "class") props.className = value;
        else if (name === "style") {
          const style: Record<string, string> = {};
          for (const property of node.style)
            style[property.replace(/-([a-z])/g, (_, letter: string) => letter.toUpperCase())] =
              node.style.getPropertyValue(property);
          props.style = style as CSSProperties;
        } else props[name] = value;
      }
      return createElement(node.tagName.toLowerCase(), props, ...[...node.childNodes].map(render));
    }
    return [...document.body.childNodes].map(render);
  }, [html]);
  return <Fragment>{children}</Fragment>;
}
