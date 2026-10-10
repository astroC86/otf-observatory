import { useLayoutEffect, useRef, type DialogHTMLAttributes } from "react";
export function Dialog({ open = false, ...props }: DialogHTMLAttributes<HTMLDialogElement>) {
  const ref = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);
  return <dialog ref={ref} {...props} />;
}
