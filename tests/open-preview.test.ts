import { beforeEach, expect, it, vi } from "vitest";
import { openAndroidPreview } from "../src/desktop/open-preview";
const { openPreview, openExternal } = vi.hoisted(() => ({ openPreview: vi.fn(), openExternal: vi.fn() }));
vi.mock("../vendor/hermes/apps/desktop/src/store/preview", () => ({ openPreview }));
vi.mock("../src/desktop/native-browser", () => ({ openExternal }));
beforeEach(() => vi.clearAllMocks());

it("opens remote HTML inside the app without a desktop buffer or browser bridge", async () => {
  const target = { kind: "file" as const, previewKind: "html" as const, path: "C:/qa/visual.html", source: "C:/qa/visual.html", url: "file:///C:/qa/visual.html", label: "QA visual", transient: true };
  await openAndroidPreview(target);
  expect(openPreview).toHaveBeenCalledWith({ ...target, renderMode: "preview" });
  expect(openExternal).not.toHaveBeenCalled();
});
it("keeps public URL opens on the native validated external-browser path", async () => {
  await openAndroidPreview({ kind: "url", source: "https://example.org/", url: "https://example.org/", label: "QA public site" });
  expect(openExternal).toHaveBeenCalledWith("https://example.org/");
  expect(openPreview).not.toHaveBeenCalled();
});

it("preserves Source fallback when the remote HTML could not be loaded", async () => {
  const target = { kind: "file" as const, previewKind: "html" as const, path: "C:/qa/missing.html", source: "C:/qa/missing.html", url: "file:///C:/qa/missing.html", label: "QA missing", transient: true, renderMode: "source" as const };
  await openAndroidPreview(target);
  expect(openPreview).toHaveBeenCalledWith(target);
  expect(openExternal).not.toHaveBeenCalled();
});
