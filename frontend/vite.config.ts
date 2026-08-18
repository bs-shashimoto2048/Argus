import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [react()],
    server: {
      // Vite's default behavior selects the next available port from 5173.
      host: true,
      proxy: {
        "/api": {
          target: env.ARGUS_BACKEND_URL || "http://localhost:8000",
          changeOrigin: true,
        },
      },
    },
  };
});
