import { describe, expect, it } from "vitest";
import { capabilityCall } from "../src/desktop/capabilities";

// Calls Desktop 0.22.5 sends that the 0.3.0 contract rejected (docs/FIX-PLAN-0.3.1.md, F5).
const ok = (request: Parameters<typeof capabilityCall>[0]) => capabilityCall({ profile: "default", ...request });
const rejected = (request: Parameters<typeof capabilityCall>[0]) => expect(() => ok(request)).toThrow(/unavailable or has invalid arguments/);

describe("0.3.1 capability contract additions", () => {
  it("chat rename/pin/archive may carry the profile Desktop adds to the body", () => {
    const call = ok({ path: "/api/sessions/s1", method: "PATCH", body: { pinned: true, request_id: "r1", expected_revision: 3, expected_generation: 0, profile: "default" } });
    expect(call.operation).toBe("PATCH /api/sessions/{session_id}");
    rejected({ path: "/api/sessions/s1", method: "PATCH", body: { pinned: true, profile: "../x" } });
    rejected({ path: "/api/sessions/s1", method: "PATCH", body: { pinned: true, other: 1 } });
  });

  it("Delete chat: DELETE with the mutation identity as query values and the mirrored profile hint", () => {
    const call = ok({ path: "/api/sessions/s1?profile=default&request_id=r1&expected_revision=3&expected_generation=0", method: "DELETE" });
    expect(call).toMatchObject({ operation: "DELETE /api/sessions/{session_id}", pathParams: { session_id: "s1" }, query: { request_id: "r1", expected_revision: 3, expected_generation: 0 } });
    // A hint for a different owner, an unlisted query key and a body are all refused.
    rejected({ path: "/api/sessions/s1?profile=other", method: "DELETE" });
    rejected({ path: "/api/sessions/s1?force=1", method: "DELETE" });
    rejected({ path: "/api/sessions/s1", method: "DELETE", body: {} });
    // The bulk and "empty" delete routes stay out.
    rejected({ path: "/api/sessions/empty", method: "DELETE" });
    rejected({ path: "/api/sessions/bulk-delete", method: "POST", body: { ids: ["a"] } });
  });

  it("skills hub search accepts limit 1..50 only", () => {
    expect(ok({ path: "/api/skills/hub/search?q=git&source=all&limit=20" }).query).toEqual({ q: "git", source: "all", limit: 20 });
    rejected({ path: "/api/skills/hub/search?q=git&limit=51" });
    rejected({ path: "/api/skills/hub/search?q=git&limit=0" });
  });

  it("Settings keys Desktop writes: appearance and housekeeping only, never secrets or backends", () => {
    for (const config of [
      { display: { resume_last_session: false } },
      { desktop: { font_family: "Inter, sans-serif" } },
      { terminal: { font_family: "Menlo" } },
      { sessions: { auto_archive: true, auto_archive_days: 7 } },
    ])
      expect(ok({ path: "/api/config", method: "PUT", body: { config } }).operation).toBe("PUT /api/config");
    expect(ok({ path: "/api/config?preserve_language=true", method: "PUT", body: { config: { display: { language: "ka" } } } }).query).toEqual({ preserve_language: true });
    for (const config of [
      { model: { api_key: "x" } },
      { terminal: { backend: "ssh" } },
      { browser: { use_real_profile: false } }, // privacy switch on the PC: not changeable from the phone
      { browser: { cdp_url: "http://x" } },
      { sessions: { auto_archive_days: 0 } },
      { env: {} },
      { providers: {} },
    ])
      rejected({ path: "/api/config", method: "PUT", body: { config } });
  });

  it("Settings model change: provider, model and scope; no endpoint URL or key", () => {
    const call = ok({ path: "/api/model/set", method: "POST", body: { scope: "main", provider: "openai", model: "gpt-5" } });
    expect(call.operation).toBe("POST /api/model/set");
    expect(ok({ path: "/api/model/set", method: "POST", body: { scope: "auxiliary", task: "vision", provider: "auto", model: "", confirm_expensive_model: true } }).operation).toBe("POST /api/model/set");
    rejected({ path: "/api/model/set", method: "POST", body: { scope: "main", provider: "custom", model: "m", api_key: "k" } });
    rejected({ path: "/api/model/set", method: "POST", body: { scope: "main", provider: "custom", model: "m", base_url: "http://x" } });
    rejected({ path: "/api/model/set", method: "POST", body: { scope: "other", provider: "p", model: "m" } });
  });

  it("cron: pause, resume and delete only; create, edit and run-now stay out", () => {
    expect(ok({ path: "/api/cron/jobs/abc123/pause", method: "POST" }).operation).toBe("POST /api/cron/jobs/{job_id}/pause");
    expect(ok({ path: "/api/cron/jobs/abc123/resume", method: "POST" }).operation).toBe("POST /api/cron/jobs/{job_id}/resume");
    expect(ok({ path: "/api/cron/jobs/abc123", method: "DELETE" }).operation).toBe("DELETE /api/cron/jobs/{job_id}");
    rejected({ path: "/api/cron/jobs", method: "POST", body: { prompt: "x" } });
    rejected({ path: "/api/cron/jobs/abc123", method: "PUT", body: { prompt: "x" } });
    rejected({ path: "/api/cron/jobs/abc123/trigger", method: "POST" });
  });
});
