import type {
  TransferGroup,
  TransferKey,
  TransferSummaryResponse,
} from "../../../api/types/transfers";
import { bytes } from "../../../lib/format/bytes";

export const TRANSFER_TYPES: Readonly<Record<string, string>> = {
  "-2": "MPI",
  "-3": "RMA Put",
  "-4": "RMA Get",
  "0": "Atomic accumulate",
  "1": "Atomic increment",
  "2": "Atomic test and set",
  "3": "Atomic compare and swap",
  "4": "Atomic swap",
  "5": "Atomic fetch and add",
  "6": "Atomic fetch and increment",
  "7": "Atomic fetch and accumulate",
};

export const transferTypeOptions = [
  ["", "MPI and RMA"],
  ["-2", "MPI"],
  ["-3,-4,0,1,2,3,4,5,6,7", "RMA"],
  ["-3", "RMA Put"],
  ["-4", "RMA Get"],
] as const;

export const summaryGroups = [
  ["size", "Payload size"],
  ["tag", "Tag"],
  ["type", "Transfer type"],
  ["communicator", "Communicator"],
  ["callsite", "Source position"],
] as const;

export const timelineGroups = [
  summaryGroups[2],
  summaryGroups[0],
  summaryGroups[1],
  summaryGroups[3],
  summaryGroups[4],
] as const;

export interface TransferWidgetProps<Data> {
  readonly data: Data | null;
  readonly error: string | null;
}

export function transferLabel(
  key: TransferKey,
  group: TransferGroup,
  callsites: TransferSummaryResponse["callsites"] | undefined,
): string {
  if (group === "size") return bytes(Number(key));
  if (group === "type") return TRANSFER_TYPES[key] || `Type ${key}`;
  if (group === "callsite") {
    if (String(key) === "-1") return "No recorded source position";
    const source = callsites?.[key];
    if (source) return `${source.file || "Source file " + source.fileRef}:${source.line}`;
  }
  return String(key);
}

export function transferRate(value: number | null | undefined): string {
  return value == null ? "—" : `${bytes(value)}/s`;
}
