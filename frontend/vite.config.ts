import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [react()],
    server: {
      // Issue #26: the port is pinned (not Vite's auto-increment-from-5173
      // default) and strictPort makes a conflict a loud startup failure
      // instead of a silent shift to a different port. A LAN client only
      // knows this one fixed URL; if the port were allowed to float (e.g.
      // to 5181 because something else is already using 5180), LAN users
      // would silently be pointed at a stale/wrong URL with no way to
      // discover the real one short of reading this PC's own terminal.
      // 5180 matches this deployment's existing convention (see README).
      port: 5180,
      strictPort: true,
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
