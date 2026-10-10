import { getState, updateState } from "./store";
import { persistState } from "./persistence";
import { notify } from "./uiActions";
import { render } from "./viewActions";
export function addBookmark() {
  const state = getState();
  if (!state.meta) return;
  const name = prompt("Bookmark name", `Selection ${state.bookmarks.length + 1}`);
  if (!name) return;
  updateState({
    bookmarks: [
      ...state.bookmarks,
      {
        name,
        start: state.start,
        end: state.end,
        locations: [...state.locations],
      },
    ],
  });
  persistState("bookmarks");
  notify("Bookmark saved");
  if (state.view === "markers") render();
}
