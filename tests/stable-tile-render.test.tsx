// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import { atom } from "nanostores";
import { createElement, useEffect } from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { paneMirror } from "../vendor/hermes/apps/desktop/src/app/chat/pane-mirror";
import { registry } from "../vendor/hermes/apps/desktop/src/contrib/registry";
import { ContribRender } from "../vendor/hermes/apps/desktop/src/contrib/react/boundary";
import { patchStableTileRender } from "../src/desktop/stable-tile-render";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("session tab body on a title change", () => {
  it("keeps the tab body mounted when the tab is registered again with a new title", async () => {
    const tiles = atom([{ id: "t1" }]);
    const titles = atom<Record<string, string>>({ t1: "New session" });
    let mounts = 0;
    let unmounts = 0;
    function Body() {
      useEffect(() => {
        mounts++;
        return () => void unmounts++;
      }, []);
      return null;
    }
    paneMirror({
      source: tiles,
      also: [titles],
      key: (t) => t.id,
      prefix: "stable-render-test",
      minWidth: "20rem",
      title: (key) => titles.get()[key] ?? "",
      render: () => createElement(Body),
      close: () => undefined,
    })();
    const pane = () => registry.getArea("panes").find((c) => c.id === "stable-render-test:t1")!;
    const first = pane().render!;
    const host = document.createElement("div");
    const root = createRoot(host);
    await act(async () => root.render(createElement(ContribRender, { render: pane().render! })));
    // The first message gives the tab its title: Desktop registers the pane again.
    titles.set({ t1: "Test from Claude" });
    expect(pane().title).toBe("Test from Claude");
    await act(async () => root.render(createElement(ContribRender, { render: pane().render! })));
    expect({ mounts, unmounts }).toEqual({ mounts: 1, unmounts: 0 });
    expect(pane().render).toBe(first);
    await act(async () => root.unmount());
  });

  it("fails the build when the pinned Desktop source moves", () => {
    const id = "/x/vendor/hermes/apps/desktop/src/app/chat/pane-mirror.ts";
    expect(() => patchStableTileRender(id, "export const x = 1")).toThrow(/pinned Desktop source changed/);
    const code = fs.readFileSync("vendor/hermes/apps/desktop/src/app/chat/pane-mirror.ts", "utf8");
    expect(patchStableTileRender(id, code)).toContain("render: renderFor(key)");
    // The rebuild comes from drawing a pane with createElement(render); fail here if Desktop changes that.
    const boundary = fs.readFileSync("vendor/hermes/apps/desktop/src/contrib/react/boundary.tsx", "utf8");
    expect(boundary).toContain("return createElement(render)");
  });
});
