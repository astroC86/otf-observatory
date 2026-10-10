import { useContext, type ReactNode } from "react";
import { containsEmbedTarget, EmbeddedCardContext } from "../../embed/target";
import { useEmbedHidden } from "../../embed/useEmbedHidden";
import { useEmbedPresence } from "../../embed/useEmbedPresence";
import { ControlBar } from "../controls/ControlBar";
import type { ControlSpec } from "../controls/types";
export interface CardProps {
  title: ReactNode;
  children: ReactNode;
  tools?: ReactNode;
  controls?: readonly ControlSpec[];
  caption?: ReactNode;
}
export function Card({ title, children, tools, controls, caption }: CardProps) {
  const selected = containsEmbedTarget([children, tools]);
  const inherited = useContext(EmbeddedCardContext);
  const hidden = useEmbedHidden(selected);
  useEmbedPresence(selected);
  return (
    <EmbeddedCardContext.Provider value={selected || inherited}>
      <section className="card" data-embed-hidden={hidden || undefined}>
        <header className="card-header">
          <h2>{title}</h2>
          <div className="tools">
            {controls ? <ControlBar className={null} controls={controls} /> : tools}
          </div>
        </header>
        {children}
        {caption ? <div className="card-caption">{caption}</div> : null}
      </section>
    </EmbeddedCardContext.Provider>
  );
}
