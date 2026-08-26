import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Vitest doesn't inject test globals here (tests import from "vitest"
// explicitly), so @testing-library/react's automatic afterEach(cleanup)
// registration -- which relies on a global `afterEach` -- never fires on
// its own. Without this, DOM from one test's render() leaks into the next.
afterEach(() => {
  cleanup();
});
