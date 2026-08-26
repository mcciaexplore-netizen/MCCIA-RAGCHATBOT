import path from "node:path";
import { defineConfig } from "vitest/config";

const dirname = import.meta.dirname;

export default defineConfig({
  test: {
    environment: "node",
    setupFiles: ["./vitest.setup.ts"],
  },
  resolve: {
    alias: {
      "@": path.resolve(dirname, "./src"),
      // Outside Next.js's own bundler, "server-only" always resolves to its
      // throwing default export (it only no-ops under the "react-server"
      // export condition Next sets). Point it at the package's own no-op
      // variant so tests can exercise server-only modules directly.
      "server-only": path.resolve(dirname, "node_modules/server-only/empty.js"),
    },
  },
});
