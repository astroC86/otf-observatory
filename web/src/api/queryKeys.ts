import type { ApiParams } from "./types/common";
import type { ViewState } from "../state/types";
export type RequestKey = readonly [
  "trace-api",
  string,
  readonly (readonly [string, string])[],
  string,
];
function request(path: string, params: ApiParams = {}, body?: unknown): RequestKey {
  // Entry order and String(value) match the raw transport's URLSearchParams.
  return [
    "trace-api",
    path,
    Object.entries(params).map(([key, value]) => [key, String(value)]),
    body ? JSON.stringify(body) : "",
  ];
}
export const queryKeys = {
  request,
  traces: () => request("traces", {}),
  status: (id: string) => request("status", { id }),
  meta: (id: string) => request("meta", { id }),
  overview: (id: string, params: ApiParams = {}) => request("overview", { id, ...params }),
  span: (id: string, params: ApiParams) => request("span", { id, ...params }),
  summary: (id: string, scope: ApiParams) => request("summary", { id, ...scope }),
  timeline: (id: string, scope: ApiParams) => request("timeline", { id, ...scope }),
  calltree: (id: string, scope: ApiParams) => request("calltree", { id, ...scope }),
  processes: (id: string, scope: ApiParams) => request("processes", { id, ...scope }),
  counters: (id: string, scope: ApiParams) => request("counters", { id, ...scope }),
  derived: (id: string, scope: ApiParams) => request("derived", { id, ...scope }),
  messages: (id: string, scope: ApiParams) => request("messages", { id, ...scope }),
  collectives: (id: string, scope: ApiParams) => request("collectives", { id, ...scope }),
  events: (id: string, scope: ApiParams) => request("events", { id, ...scope }),
  markers: (id: string, scope: ApiParams) => request("markers", { id, ...scope }),
  definitions: (id: string, scope: ApiParams) => request("definitions", { id, ...scope }),
  view: (snapshot: ViewState) => {
    const {
      view,
      meta,
      epoch,
      history,
      historyIndex,
      collapsed,
      selectedRegion,
      colors,
      bookmarks,
      tableSearch,
      dockLayout,
      locations,
      ...settings
    } = snapshot;
    return ["view", view, { ...settings, locations: [...locations] }] as const;
  },
};
