import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  // Mirrors tsconfig "paths" so components importing "@/lib/..." (the teacher
  // Quiz pages) can be rendered in tests too.
  resolve: {
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
    setupFiles: ["tests/setup.ts"],
    // Full jsdom runs on a loaded laptop starve individual workers; these limits
    // bound waiting time only and never relax what a test asserts.
    testTimeout: 20_000,
  },
});
