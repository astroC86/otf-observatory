import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "./api/queryClient";
import App from "./App";
import Bootstrap from "./Bootstrap";
const root = document.getElementById("root");
if (!root) throw Error("The application root is missing.");
createRoot(root).render(
  <QueryClientProvider client={queryClient}>
    <App />
    <Bootstrap />
  </QueryClientProvider>,
);
