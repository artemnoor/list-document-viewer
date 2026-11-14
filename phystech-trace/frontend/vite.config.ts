import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { integratedSite } from "./scripts/integrated-site";

export default defineConfig({
  base: "/app/",
  plugins: [vue(), integratedSite()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8084", "/health": "http://127.0.0.1:8084" },
  },
  build: { outDir: "dist/app", sourcemap: false },
});
