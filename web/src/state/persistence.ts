import { getState } from "./store";
import type { AppState } from "./types";

// Persist only explicit preference actions. Session restore must not overwrite
// the separate colors/bookmarks records or introduce a whole-store JSON key.
export function readTracePreferences(path: string) {
  return {
    bookmarks: JSON.parse(
      localStorage.getItem("bookmarks:" + path) || "[]",
    ) as AppState["bookmarks"],
    colors: JSON.parse(localStorage.getItem("colors") || "{}") as AppState["colors"],
  };
}
export function persistState(kind: "colors" | "bookmarks"): void {
  const state = getState();
  if (kind === "colors") localStorage.setItem("colors", JSON.stringify(state.colors));
  else if (state.meta)
    localStorage.setItem("bookmarks:" + state.meta.path, JSON.stringify(state.bookmarks));
}
