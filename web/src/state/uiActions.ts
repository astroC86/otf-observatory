import { getUi, updateUi } from "./store";

let toastTimer = 0;
export function notify(message: string) {
  updateUi({ toast: message });
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => updateUi({ toast: null }), 4200);
}
export function applyTheme(theme: string | null): void {
  updateUi({ theme: theme === "dark" ? "dark" : "light" });
}
export function toggleTheme() {
  const theme = getUi().theme === "dark" ? "light" : "dark";
  applyTheme(theme);
  localStorage.setItem("theme", theme);
}
export function toggleSidebar() {
  updateUi({ sidebarCollapsed: !getUi().sidebarCollapsed });
}
