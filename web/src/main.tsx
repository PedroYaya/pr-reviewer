import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1 } },
});

// Mocks are on by default; `npm run dev:api` talks to the real reviewer service.
async function enableMocks() {
  if (import.meta.env.DEV && import.meta.env.VITE_MOCKS !== "false") {
    const { startMocks } = await import("./mocks/browser");
    await startMocks();
  }
}

enableMocks().then(() => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </StrictMode>,
  );
});
