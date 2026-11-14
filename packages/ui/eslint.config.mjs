import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // Rules introduced by eslint-config-next 16 (TypeScript preset and the
    // React Compiler-aware react-hooks v7 rules) that flag existing code in
    // app/page.tsx and the diff viewers. They are reported as warnings so they
    // stay visible in every lint run while the dashboard is split into smaller
    // components and properly typed in #275; promote them back to "error" once
    // that refactor lands.
    rules: {
      "@typescript-eslint/no-explicit-any": "warn",
      "react-hooks/immutability": "warn",
      "react-hooks/set-state-in-effect": "warn",
    },
  },
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
]);
