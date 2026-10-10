import { createContext } from "react";
import type { ViewState } from "../state/types";

// A deferred view and its queries must read the same immutable selection.
export const ViewStateContext = createContext<ViewState | null>(null);
