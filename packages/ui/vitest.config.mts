import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL(".", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/support/setup.ts"],
    include: ["tests/unit/**/*.test.{ts,tsx}"],
    restoreMocks: true,
    unstubGlobals: true,
    coverage: {
      provider: "v8",
      include: ["store/**", "lib/**", "hooks/**", "components/**", "app/**"],
      reporter: ["text-summary", "text"],
      // #275 acceptance: at least 60% line coverage on store/ and lib/.
      thresholds: {
        "store/**": { lines: 60 },
        "lib/**": { lines: 60 },
      },
    },
  },
});
