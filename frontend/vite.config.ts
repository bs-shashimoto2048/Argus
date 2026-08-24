import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [react()],
    server: {
      // Vite's default behavior selects the next available port from 5173.
      // host:true binds all network interfaces (0.0.0.0), so this dev server is
      // reachable from other PCs on the same LAN (Issue #26: occasional access
      // from another in-office PC, not a production deployment). The Backend
      // itself stays bound to 127.0.0.1 (Uvicorn's default when --host is not
      // given) and is never exposed to the LAN directly; all /api/** calls from
      // the browser are relative and proxied server-side to the Backend below,
      // so a LAN client only ever needs this single Frontend URL/port.
      // There is no authentication anywhere in Argus, so anyone who can reach
      // this port on the LAN can also change settings, not just view them.
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
