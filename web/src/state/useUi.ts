import { useStore } from "zustand";
import { useShallow } from "zustand/react/shallow";
import { appStore } from "./store";
import type { UiState } from "./types";
export function useUi<T>(selector: (value: Readonly<UiState>) => T): T {
  return useStore(
    appStore,
    useShallow((store) => selector(store.ui)),
  );
}
