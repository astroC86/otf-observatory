import { getState, getUi } from "./store";
import { groupColors, palette } from "../lib/color/palette";
import { hash } from "../lib/color/hash";
import type {
  TraceMeta,
  RegionDefinition,
  LocationDefinition,
  GroupDefinition,
} from "../api/types/common";
interface Catalog {
  regions: Record<string, RegionDefinition>;
  locations: Record<string, LocationDefinition>;
  groups: Record<string, GroupDefinition>;
}
const catalogs = new WeakMap<TraceMeta, Catalog>();
const empty: Catalog = { regions: {}, locations: {}, groups: {} };
function catalog() {
  const meta = getState().meta;
  if (!meta) return empty;
  let value = catalogs.get(meta);
  if (!value) {
    value = {
      regions: Object.fromEntries(meta.regions.map((region) => [region.id, region])),
      locations: Object.fromEntries(meta.locations.map((location) => [location.id, location])),
      groups: Object.fromEntries(meta.groups.map((group) => [group.id, group])),
    };
    catalogs.set(meta, value);
  }
  return value;
}
function catalogMap<Key extends keyof Catalog>(key: Key): Readonly<Catalog[Key]> {
  return new Proxy({} as Catalog[Key], {
    get: (_target, property) => Reflect.get(catalog()[key], property),
    ownKeys: () => Reflect.ownKeys(catalog()[key]),
    getOwnPropertyDescriptor: (_target, property) => ({
      configurable: true,
      enumerable: true,
      value: Reflect.get(catalog()[key], property),
    }),
  });
}
export const regions = catalogMap("regions");
export const locations = catalogMap("locations");
export const groups = catalogMap("groups");
export const getOverviewData = () => getUi().overviewData;
export function color(id: string | number | null | undefined, byGroup = false): string {
  return groupColor(String(byGroup ? regions[String(id)]?.group : id));
}
export function groupColor(group: string, colors = getState().colors): string {
  return colors[group] || groupColors[group] || palette[hash(group) % palette.length]!;
}
export function locName(id: string | number | null | undefined): string {
  const location = locations[String(id)];
  return location
    ? `${groups[location.group]?.name || `Process ${location.group}`} · ${location.name}`
    : String(id ?? "Unresolved");
}
export const shortLoc = locName;
