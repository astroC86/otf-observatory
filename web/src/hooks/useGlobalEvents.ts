import { useEffect } from "react";
import { redrawCharts } from "../charts/redraw";
import { addBookmark } from "../state/bookmarks";
import { moveHistory, setRange, zoom } from "../state/rangeActions";
import { setView } from "../state/viewActions";
import { getWorkspace } from "../workspace/store";
import { getState, getUi, updateUi } from "../state/store";
import { usePreserveScroll } from "./usePreserveScroll";

export function useGlobalEvents(): void {
  usePreserveScroll();
  useEffect(() => {
    let resizeTimer: number | undefined;
    const onStorage = (event: StorageEvent) => {
      if (event.storageArea === localStorage && (event.key === "theme" || event.key === null)) {
        updateUi({
          theme: event.key !== null && event.newValue === "dark" ? "dark" : "light",
        });
      }
    };
    const onClick = (event: MouseEvent) => {
      const insideMenu = event
        .composedPath()
        .some(
          (node) => node instanceof Element && (node.id === "context-menu" || node.id === "export"),
        );
      if (!insideMenu && getUi().menu) updateUi({ menu: null });
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        (target instanceof Element && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) ||
        getUi().dialog ||
        getWorkspace().dialog
      )
        return;
      if (event.key === "Escape") updateUi({ contextVisible: false, menu: null, tooltip: null });
      if (event.key === "+" || event.key === "=") zoom(0.5);
      if (event.key === "-") zoom(2);
      if (event.key === "Home") {
        event.preventDefault();
        const { meta } = getState();
        if (meta) setRange(0, meta.duration);
      }
      if (event.altKey && event.key === "ArrowLeft") {
        event.preventDefault();
        moveHistory(-1);
      }
      if (event.altKey && event.key === "ArrowRight") {
        event.preventDefault();
        moveHistory(1);
      }
      if (event.key.toLowerCase() === "b") addBookmark();
      if (event.key === "?") updateUi({ dialog: "help" });
    };
    const onResize = () => {
      clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(redrawCharts, 100);
    };
    const onHashChange = () => {
      const next = location.hash.slice(1);
      if (next && next !== getState().view) setView(next);
    };
    window.addEventListener("storage", onStorage);
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", onResize);
    window.addEventListener("hashchange", onHashChange);
    return () => {
      clearTimeout(resizeTimer);
      window.removeEventListener("storage", onStorage);
      document.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("hashchange", onHashChange);
    };
  }, []);
}
