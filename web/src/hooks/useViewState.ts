import { useContext } from "react";
import { ViewStateContext } from "../views/ViewStateContext";
import type { ViewState } from "../state/types";
export function useViewState(): ViewState {
  const view = useContext(ViewStateContext);
  if (!view) throw Error("An analysis view requires a loaded trace");
  return view;
}
