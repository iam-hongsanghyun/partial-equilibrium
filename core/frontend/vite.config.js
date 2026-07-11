import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

const repoRoot = resolve(__dirname, "..", "..");   // core/frontend -> core -> repo

export default defineConfig({
  root: __dirname,                                 // core/frontend
  plugins: [react()],
  publicDir: resolve(__dirname, "public"),
  resolve: {
    alias: {
      "@core": resolve(__dirname, "src"),          // shell primitives
      "@features": resolve(repoRoot, "modules"),   // module fragments
    },
  },
  server: { fs: { allow: [repoRoot] } },           // dev server may read modules/* outside root
  build: { outDir: resolve(__dirname, "dist"), emptyOutDir: true },
});
