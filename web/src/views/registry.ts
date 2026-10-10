import type { ComponentType } from "react";
import { TimelineView } from "./timeline/TimelineView";
import { FunctionsView } from "./functions/FunctionsView";
import { CalltreeView } from "./calltree/CalltreeView";
import { ProcessesView } from "./processes/ProcessesView";
import { CountersView } from "./counters/CountersView";
import { RadarView } from "./radar/RadarView";
import { CommunicationView } from "./communication/CommunicationView";
import { CollectivesView } from "./collectives/CollectivesView";
import { IoView } from "./io/IoView";
import { SystemView } from "./system/SystemView";
import { EventsView } from "./events/EventsView";
import { MarkersView } from "./markers/MarkersView";
import { TraceView } from "./trace/TraceView";
import { MetricStudio } from "./metrics/MetricStudio";
import { WaitsView } from "./waits/WaitsView";
import { RelationshipView } from "./dependencies/RelationshipView";
import { CompareView } from "./compare/CompareView";
export const viewComponents: Record<string, ComponentType> = {
  timeline: TimelineView,
  functions: FunctionsView,
  calltree: CalltreeView,
  processes: ProcessesView,
  counters: CountersView,
  radar: RadarView,
  communication: CommunicationView,
  collectives: CollectivesView,
  io: IoView,
  system: SystemView,
  events: EventsView,
  markers: MarkersView,
  trace: TraceView,
  metrics: MetricStudio,
  waits: WaitsView,
  dependencies: RelationshipView,
  gpu: RelationshipView,
  compare: CompareView,
};
