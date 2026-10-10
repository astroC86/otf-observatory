import { useEffect } from "react";
import { appStore, getState, getUi } from "../state/store";

const SCROLL_KEYS: Record<string, true> = {
  ArrowUp: true,
  ArrowDown: true,
  PageUp: true,
  PageDown: true,
  Home: true,
  End: true,
  " ": true,
};

type Offset = readonly [number, number];

/** Scroll offsets of the page and of each scrolled container inside #view, for one view. */
interface Positions {
  page: Offset;
  containers: Map<string, Offset>;
}

/** Stable key of a scroll container: its id, else its child-index path below #view. */
function containerKey(element: Element, root: Element): string {
  if (element.id) return `#${element.id}`;
  const path: number[] = [];
  for (
    let node: Element = element;
    node !== root && node.parentElement;
    node = node.parentElement
  ) {
    path.push(Array.prototype.indexOf.call(node.parentElement.children, node));
  }
  return path.reverse().join("/");
}

function findContainer(root: Element, key: string): Element | null {
  if (key.startsWith("#")) {
    const element = document.getElementById(key.slice(1));
    return element && root.contains(element) ? element : null;
  }
  let node: Element | null = root;
  for (const index of key.split("/")) node = node?.children[Number(index)] ?? null;
  return node;
}

/**
 * Keep every tab's scroll position — the page and scrolled tables/panels inside the view —
 * across re-renders (range/filter changes, resizes) and when returning to a tab.
 * Any user scroll gesture cancels a pending restore.
 */
export function usePreserveScroll(): void {
  useEffect(() => {
    const saved = new Map<string, Positions>();
    let pending = false;
    let frame = 0;
    let generation = 0;
    let userScrolled = false;
    let displayed = `${getState().id}:${getState().view}`;
    const remember = (event: Event) => {
      // While a view loads, collapsing content clamps offsets; those are not user positions.
      if (pending || (getUi().busy && !userScrolled)) return;
      const name = displayed;
      let entry = saved.get(name);
      if (!entry) saved.set(name, (entry = { page: [scrollX, scrollY], containers: new Map() }));
      const view = document.getElementById("view");
      const target = event.target;
      if (target === document || target === document.documentElement) {
        entry.page = [scrollX, scrollY];
      } else if (view && target instanceof Element && view.contains(target)) {
        entry.containers.set(containerKey(target, view), [target.scrollLeft, target.scrollTop]);
      }
    };
    const capture = () => {
      let entry = saved.get(displayed);
      if (!entry) saved.set(displayed, (entry = { page: [0, 0], containers: new Map() }));
      // A scroll event may still be queued when history commits in the same frame.
      entry.page = [scrollX, scrollY];
      const view = document.getElementById("view");
      if (!view) return;
      for (const key of entry.containers.keys()) {
        const element = findContainer(view, key);
        if (element) entry.containers.set(key, [element.scrollLeft, element.scrollTop]);
      }
    };
    const apply = () => {
      const state = getState();
      const entry = saved.get(`${state.id}:${state.view}`);
      const view = document.getElementById("view");
      if (!entry || !view) return;
      window.scrollTo(entry.page[0], entry.page[1]);
      for (const [key, [left, top]] of entry.containers) {
        findContainer(view, key)?.scrollTo(left, top);
      }
    };
    const restore = () => {
      if (!pending || getUi().busy) return;
      cancelAnimationFrame(frame);
      const requested = generation;
      frame = requestAnimationFrame(() => {
        if (!pending || getUi().busy || requested !== generation) return;
        apply();
        pending = false;
      });
    };
    const expectRender = () => {
      generation++;
      cancelAnimationFrame(frame);
      const state = getState();
      userScrolled = false;
      pending = saved.has(`${state.id}:${state.view}`);
    };
    const cancel = () => {
      pending = false;
      userScrolled = true;
      cancelAnimationFrame(frame);
    };
    const key = (event: KeyboardEvent) => {
      if (SCROLL_KEYS[event.key]) cancel();
    };
    const onResize = () => {
      expectRender();
      restore();
    };
    const unsubscribe = appStore.subscribe((current, previous) => {
      if (
        current.state.id !== previous.state.id ||
        current.state.view !== previous.state.view ||
        current.ui.epoch !== previous.ui.epoch ||
        (current.ui.busy && !previous.ui.busy)
      ) {
        if (!previous.ui.busy) capture();
        expectRender();
      } else if (previous.ui.busy && !current.ui.busy) {
        displayed = `${current.state.id}:${current.state.view}`;
        if (pending) restore();
      }
    });
    window.addEventListener("scroll", remember, { capture: true, passive: true });
    window.addEventListener("resize", onResize);
    window.addEventListener("wheel", cancel, { passive: true });
    window.addEventListener("touchmove", cancel, { passive: true });
    window.addEventListener("pointerdown", cancel);
    document.addEventListener("keydown", key);
    return () => {
      unsubscribe();
      cancel();
      window.removeEventListener("scroll", remember, { capture: true });
      window.removeEventListener("resize", onResize);
      window.removeEventListener("wheel", cancel);
      window.removeEventListener("touchmove", cancel);
      window.removeEventListener("pointerdown", cancel);
      document.removeEventListener("keydown", key);
    };
  }, []);
}
