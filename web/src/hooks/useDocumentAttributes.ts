import { useLayoutEffect } from "react";
import { redrawCharts } from "../charts/redraw";
import { useUi } from "../state/useUi";

export function useDocumentAttributes(): void {
  const { theme, sidebarCollapsed, embedded } = useUi(({ theme, sidebarCollapsed, embedded }) => ({
    theme,
    sidebarCollapsed,
    embedded,
  }));
  useLayoutEffect(() => {
    const body = document.body;
    const root = document.documentElement;
    const previous = {
      dark: body.classList.contains("dark"),
      sidebar: body.classList.contains("sidebar-collapsed"),
      embedded: root.classList.contains("embedded-chart"),
      theme: root.getAttribute("data-theme"),
      colorScheme: root.style.getPropertyValue("color-scheme"),
      colorSchemePriority: root.style.getPropertyPriority("color-scheme"),
    };
    body.classList.toggle("dark", theme === "dark");
    body.classList.toggle("sidebar-collapsed", sidebarCollapsed);
    root.classList.toggle("embedded-chart", embedded);
    root.dataset.theme = theme;
    root.style.colorScheme = theme;
    const frame = requestAnimationFrame(redrawCharts);
    return () => {
      cancelAnimationFrame(frame);
      body.classList.toggle("dark", previous.dark);
      body.classList.toggle("sidebar-collapsed", previous.sidebar);
      root.classList.toggle("embedded-chart", previous.embedded);
      if (previous.theme === null) root.removeAttribute("data-theme");
      else root.setAttribute("data-theme", previous.theme);
      root.style.setProperty("color-scheme", previous.colorScheme, previous.colorSchemePriority);
    };
  }, [theme, sidebarCollapsed, embedded]);
}
