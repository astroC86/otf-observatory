export function csv(rows: readonly object[]): string {
  const first = rows[0];
  if (!first) return "";
  const keys = Object.keys(first);
  const cell = (value: unknown) =>
    '"' +
    String(typeof value === "object" ? JSON.stringify(value) : (value ?? "")).replaceAll(
      '"',
      '""',
    ) +
    '"';
  return [
    keys.map(cell).join(","),
    ...rows.map((row) => keys.map((key) => cell(Reflect.get(row, key))).join(",")),
  ].join("\r\n");
}
