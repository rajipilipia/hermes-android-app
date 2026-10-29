import { describe, expect, it } from "vitest";
import fs from "node:fs";
import { patchPhoneConnectionScope } from "../src/desktop/phone-connection-scope";
// Imported through the Vite plugins, so this is the patched module the phone runs.
import { registryBackendScopeKey } from "../vendor/hermes/apps/shared/src/backend-scope";

const rel = "shared/src/backend-scope.ts";
const id = `/x/vendor/hermes/apps/${rel}`;
const code = fs.readFileSync(`vendor/hermes/apps/${rel}`, "utf8");

describe("owner routes on the one-server phone", () => {
  it("routes an explicit local owner to the profile route, like a null owner", () => {
    expect(registryBackendScopeKey("local", "example-profile")).toBe("example-profile");
    expect(registryBackendScopeKey(" local ", "example-profile")).toBe("example-profile");
    expect(registryBackendScopeKey(null, "example-profile")).toBe("example-profile");
  });

  it("keeps other source ids as separate routes", () => {
    expect(registryBackendScopeKey("remote-2", "example-profile")).toBe("conn:remote-2::example-profile");
  });

  it("fails the build when the pinned Desktop source moves", () => {
    expect(patchPhoneConnectionScope(id, code)).toContain("connection !== LOCAL_CONNECTION_ID");
    expect(() => patchPhoneConnectionScope(id, "export const x = 1")).toThrow(/pinned Desktop source changed/);
    expect(patchPhoneConnectionScope("/x/vendor/hermes/apps/shared/src/other.ts", "x")).toBeUndefined();
  });
});
