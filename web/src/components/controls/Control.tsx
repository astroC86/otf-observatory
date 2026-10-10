import { useRef, useState, type ReactNode } from "react";
import { OptionList } from "./OptionList";
import type { ControlSpec } from "./types";
import { useEmbedHidden } from "../../embed/useEmbedHidden";
export function Control({ control }: { control: ControlSpec }) {
  const incoming =
    control.kind === "checkbox"
      ? control.checked
      : "value" in control
        ? String(control.value ?? "")
        : "";
  const [draft, setDraft] = useState(() => ({
    source: incoming,
    value: incoming,
  }));
  const previous = useRef(incoming);
  if (draft.source !== incoming) {
    setDraft({ source: incoming, value: incoming });
    previous.current = incoming;
  }
  const value = draft.source === incoming ? draft.value : incoming;
  const hidden = useEmbedHidden();
  if (control.kind === "content") return control.children;
  const attributes = Object.fromEntries(
    Object.entries(control.data || {}).map(([key, value]) => ["data-" + key, value]),
  );
  const props = {
    id: control.id,
    className: control.className,
    title: control.title,
    "aria-label": control.ariaLabel,
    "aria-pressed": control.ariaPressed,
    disabled: control.disabled,
    "data-embed-hidden": hidden || undefined,
    ...attributes,
  };
  let element: ReactNode;
  if (control.kind === "button")
    element = (
      <button {...props} type={control.type} onClick={control.onClick}>
        {control.children}
      </button>
    );
  else if (control.kind === "select")
    element = (
      <select
        {...props}
        value={String(value)}
        onChange={(event) => {
          const value = event.currentTarget.value;
          setDraft((previous) => ({ ...previous, value }));
          control.onChange(value);
        }}
      >
        <OptionList items={control.options} />
      </select>
    );
  else if (control.kind === "checkbox")
    element = (
      <input
        {...props}
        type="checkbox"
        checked={value === true}
        onChange={(event) => {
          const value = event.currentTarget.checked;
          setDraft((previous) => ({ ...previous, value }));
          control.onChange(value);
        }}
      />
    );
  else
    element = (
      <input
        {...props}
        type={control.kind === "text" ? undefined : control.kind}
        value={String(value)}
        min={control.min}
        max={control.max}
        step={control.step}
        size={control.size}
        placeholder={control.placeholder}
        list={control.list}
        onChange={(event) => {
          const value = event.currentTarget.value;
          setDraft((previous) => ({ ...previous, value }));
          if (control.event !== "change") control.onChange?.(value);
        }}
        onKeyDown={control.onKeyDown}
        onBlur={(event) => {
          if (control.event === "change" && event.currentTarget.value !== previous.current) {
            previous.current = event.currentTarget.value;
            control.onChange?.(event.currentTarget.value);
          }
        }}
      />
    );
  if (control.label == null)
    return (
      <>
        {element}
        {control.suffix}
      </>
    );
  return (
    <label className={control.labelClassName}>
      {control.labelAfter ? (
        <>
          {element}
          {control.suffix}
          {control.label}
        </>
      ) : (
        <>
          {typeof control.label === "string" ? `${control.label} ` : control.label}
          {element}
          {control.suffix}
        </>
      )}
    </label>
  );
}
