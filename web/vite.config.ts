import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: `npm run dev` on :5173 proxies /api to the FastAPI server.
// Prod: `npm run build` writes web/dist, which FastAPI serves at /.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": process.env.API_URL || "http://localhost:8010" },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: { manualChunks: { react: ["react", "react-dom"], motion: ["framer-motion"], gsap: ["gsap", "@gsap/react"], graph: ["cytoscape"] } },
    },
  },
});
