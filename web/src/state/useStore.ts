import { useStore as useZustandStore } from "zustand";
import { useShallow } from "zustand/react/shallow";
import { appStore } from "./store";
import type { AppState } from "./types";
export function useStore<T>(selector: (value: Readonly<AppState>) => T): T {
  return useZustandStore(
    appStore,
    useShallow((store) => selector(store.state)),
  );
}
