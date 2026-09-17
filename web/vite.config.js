import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// The build lands in ../static/dist, which the Python server serves directly.
// That is what keeps deployment to a single command: once this has run, the
// server needs nothing from Node at all.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    outDir: path.resolve(__dirname, "../static/dist"),
    emptyOutDir: true,
    // Source maps are worth the size here: when a scan misbehaves on a shop
    // floor laptop, a readable stack trace is the difference between a
    // five-minute fix and an afternoon.
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          charts: ["recharts"],
          scanner: ["html5-qrcode"],
        },
      },
    },
  },
  server: {
    port: 5173,
    // `npm run dev` gives hot reload while still talking to the real Python API.
    proxy: { "/api": "http://localhost:8000" },
  },
});
