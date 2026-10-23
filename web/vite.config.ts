import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// With mocks off (`npm run dev:api`), /api goes to the reviewer service.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8001" },
  },
});
