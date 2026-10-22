import { beforeEach, expect, it, vi } from "vitest";
const qa = vi.hoisted(() => ({
  state: undefined as undefined | { model: string; provider: string; reasoningEffort: string; fast: boolean; serviceTier: string },
  stored: null as string | null,
  owner: vi.fn(),
  notify: vi.fn(),
  model: "draft-model", provider: "draft-provider", effort: "high", profile: "research",
}));
vi.mock("../vendor/hermes/apps/desktop/src/app/chat/session-view", () => ({ PRIMARY_SESSION_VIEW: {
  $model: { get: () => qa.model }, $provider: { get: () => qa.provider },
  $reasoningEffort: { get: () => qa.effort }, $fast: { get: () => false }, $serviceTier: { get: () => "" },
} }));
vi.mock("../vendor/hermes/apps/desktop/src/app/session/hooks/use-session-actions/utils", () => ({ resolveSessionOwner: qa.owner }));
vi.mock("../vendor/hermes/apps/desktop/src/store/notifications", () => ({ notifyError: qa.notify }));
vi.mock("../vendor/hermes/apps/desktop/src/store/profile", () => ({ $activeGatewayProfile: { get: () => qa.profile } }));
vi.mock("../vendor/hermes/apps/desktop/src/store/session", () => ({ $defaultReasoningEffort: { get: () => "medium" } }));
vi.mock("../vendor/hermes/apps/desktop/src/store/session-focus", () => ({ $focusedStoredSessionId: { get: () => qa.stored } }));
vi.mock("../vendor/hermes/apps/desktop/src/store/session-states", () => ({ $focusedSessionState: { get: () => qa.state } }));
import { captureAndroidTabSelection, openAndroidNewSessionTab } from "../src/desktop/new-session-tab";

beforeEach(() => {
  qa.state = undefined; qa.stored = null; qa.model = "draft-model"; qa.effort = "high";
  qa.owner.mockReset(); qa.notify.mockReset();
});
it("opens a blank tab using the current draft selections, without changing any existing draft", async () => {
  const open = vi.fn();
  await openAndroidNewSessionTab(open);
  expect(open).toHaveBeenCalledExactlyOnceWith("center", {
    listed: false, profile: "research", route: null,
    androidSelection: { model: "draft-model", provider: "draft-provider", reasoning_effort: "high", fast: false },
  });
  expect(qa.owner).not.toHaveBeenCalled();
});
it("captures the focused tile's selections before an asynchronous owner lookup", async () => {
  qa.stored = "stored-tile";
  qa.state = { model: "tile-model", provider: "tile-provider", reasoningEffort: "low", fast: true, serviceTier: "ultrafast" };
  let release!: (owner: string) => void;
  qa.owner.mockImplementation(() => new Promise(resolve => { release = resolve; }));
  const open = vi.fn();
  const pending = openAndroidNewSessionTab(open);
  qa.state = { ...qa.state, model: "another-model", reasoningEffort: "max" };
  release("tile-profile");
  await pending;
  expect(open).toHaveBeenCalledWith("center", expect.objectContaining({
    profile: "tile-profile", route: null,
    androidSelection: { model: "tile-model", provider: "tile-provider", reasoning_effort: "low", fast: true, service_tier: "ultrafast" },
  }));
});
it("preserves an exact routed owner and never guesses the profile of an unresolved chat", async () => {
  qa.stored = "stored-tile";
  const route = { connectionId: "local", profile: "work" };
  qa.owner.mockResolvedValueOnce(route).mockResolvedValueOnce(undefined);
  const open = vi.fn();
  await openAndroidNewSessionTab(open);
  expect(open).toHaveBeenCalledWith("center", expect.objectContaining({ profile: "work", route }));
  open.mockClear();
  await openAndroidNewSessionTab(open);
  expect(open).not.toHaveBeenCalled();
  expect(qa.notify).toHaveBeenCalledOnce();
});
it("uses the configured effort only for a sessionless draft with an empty selection", () => {
  qa.effort = "";
  expect(captureAndroidTabSelection().reasoning_effort).toBe("medium");
});
