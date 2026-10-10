const numberFormats = new Map<number, Intl.NumberFormat>();
const compactFormat = new Intl.NumberFormat(undefined, {
  notation: "compact",
  maximumFractionDigits: 2,
});

export function num(value: unknown, digits = 2): string {
  if (value == null) return "—";
  let format = numberFormats.get(digits);
  if (!format) {
    format = new Intl.NumberFormat(undefined, { maximumFractionDigits: digits });
    numberFormats.set(digits, format);
  }
  return format.format(Number(value));
}

export const compact = (value: number | null | undefined) => compactFormat.format(value || 0);
