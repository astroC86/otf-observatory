import { shortLoc } from "../../state/selectors";
import type { ColumnDef } from "../../components/table/types";

export function locationCol<Row extends { readonly location: string }>(): ColumnDef<Row> {
  return {
    key: "location",
    label: "Location",
    render: (_, row) => `${shortLoc(row.location) ?? ""}`,
  };
}
