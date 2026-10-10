import { updateUi } from "../state/store";
import { useUi } from "../state/useUi";
import SpanContext from "./SpanContext";

export default function Inspector() {
  const { context, contextVisible } = useUi(({ context, contextVisible }) => ({
    context,
    contextVisible,
  }));
  return (
    <aside id="context" className="context-panel" hidden={!contextVisible}>
      <div className="panel-heading">
        <h2>Event context</h2>
        <button
          id="close-context"
          className="icon-button"
          aria-label="Close context"
          onClick={() => updateUi({ contextVisible: false })}
        >
          ×
        </button>
      </div>
      {
        <div id="context-content">
          {context?.kind === "span" ? (
            <SpanContext span={context.span} />
          ) : context?.kind === "object" ? (
            <>
              {context.before}
              <h3>{context.title}</h3>
              <pre className="code-block">{JSON.stringify(context.object, null, 2)}</pre>
              {context.after}
            </>
          ) : context?.kind === "content" ? (
            <>
              <h3>{context.title}</h3>
              {context.content}
            </>
          ) : null}
        </div>
      }
    </aside>
  );
}
