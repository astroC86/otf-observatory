import { useStore } from "zustand";
import { appStore } from "./store";
export function useCommittedView() {
  return useStore(appStore, (store) => store.committed);
}
