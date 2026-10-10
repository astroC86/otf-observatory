import type { Option } from "./types";
export function OptionList({ items }: { items: readonly Option[] }) {
  return items.map((item, index) =>
    typeof item === "string" || typeof item === "number" ? (
      <option key={index}>{item}</option>
    ) : (
      <option key={index} value={item[0]}>
        {item[1]}
      </option>
    ),
  );
}
