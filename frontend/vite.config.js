import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // Keep large libraries in their own cacheable chunks.
        manualChunks: { react: ["react", "react-dom"], sanitize: ["dompurify"] },
      },
    },
  },
  // DOMPurify needs a DOM; jsdom provides one for the sanitizer tests.
  test: { environment: "jsdom" },
});
