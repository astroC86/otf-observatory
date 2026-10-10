const pattern = /[&<>"']/g;
const entities: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};
export const esc = (value: unknown) =>
  String(value ?? "").replace(pattern, (character) => entities[character] ?? character);
