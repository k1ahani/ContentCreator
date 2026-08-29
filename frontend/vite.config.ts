import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend defaults to 8420 (see backend/app/core/config.py) because Windows
// reserves ranges around 8000-9000 for Hyper-V/WinNAT; if CCA_PORT is set,
// mirror it here so the dev-server proxy still finds the API.
const backendPort = process.env.CCA_PORT ?? "8420";

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Mirrors tsconfig.json's "paths": {"@/*": ["src/*"]} - tsc only checks
    // types with that mapping, it does not affect Vite's own module
    // resolution, so the alias has to be declared here too.
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true,
        // SSE needs the connection kept open rather than buffered.
        ws: false,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
