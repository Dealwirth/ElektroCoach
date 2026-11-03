import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Wichtig fuer Home Assistant Ingress:
//   base "./" erzeugt relative Pfade. Absolute Pfade (/assets/...) wuerden
//   hinter dem wechselnden Ingress-Pfad ins Leere zeigen.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["react", "react-dom", "react-router-dom"],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8099",
        changeOrigin: true,
      },
    },
  },
});
