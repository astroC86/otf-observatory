import { useLayoutEffect, useRef, type ReactNode } from "react";
import { TrustedMarkup } from "./components/ui/TrustedMarkup";
import { useUi } from "./state/useUi";
export default function Tooltip() {
  const tooltip = useUi((ui) => ui.tooltip);
  const ref = useRef<HTMLDivElement>(null);
  const lastContent = useRef<ReactNode>("");
  const content = tooltip ? tooltip.content : lastContent.current;
  useLayoutEffect(() => {
    const element = ref.current;
    if (!tooltip || !element) return;
    lastContent.current = tooltip.content;
    element.style.left = `${Math.min(tooltip.x + 14, innerWidth - 420)}px`;
    element.style.top = `${Math.min(tooltip.y + 14, innerHeight - element.offsetHeight - 12)}px`;
  }, [tooltip?.x, tooltip?.y, tooltip?.content]);
  return (
    <div id="tooltip" ref={ref} className="tooltip" hidden={!tooltip}>
      {typeof content === "string" ? <TrustedMarkup html={content} /> : content}
    </div>
  );
}
