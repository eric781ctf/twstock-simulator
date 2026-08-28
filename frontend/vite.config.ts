import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    watch: {
      // Docker Desktop on Windows doesn't reliably forward inotify events
      // from the host bind mount into the container, so native fs watching
      // silently misses file changes. Polling works around that.
      usePolling: true,
      interval: 300,
    },
  },
});
