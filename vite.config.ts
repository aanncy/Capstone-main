import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Forward /api calls to the backend once it exists (FastAPI default port assumed)
    proxy: { "/api": "http://localhost:8000" },
  },
});
