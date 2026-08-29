import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next -- leading "**/" so a stray
    // nested build-cache dir (observed: Turbopack sometimes writes a
    // duplicate web/web/.next/ in this environment, cause not tracked
    // down, harmless but pollutes lint with thousands of bundled-JS
    // findings if not excluded) is ignored at any depth, not just at
    // the config file's own directory.
    "**/.next/**",
    "**/out/**",
    "**/build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
