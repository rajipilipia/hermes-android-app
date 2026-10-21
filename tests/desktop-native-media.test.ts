// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { Blob as NodeBlob, File as NodeFile } from "node:buffer";
import { cleanup } from "@testing-library/react";
import { installDesktopHost } from "../src/desktop/host";
import { uploadComposerAttachment } from "../vendor/hermes/apps/desktop/src/app/session/hooks/use-prompt-actions";
import { resolveSpeakStreamUrl } from "../vendor/hermes/apps/desktop/src/lib/voice-playback";

// Native only: files and voice take Desktop's own remote-mode paths against Hermes itself.
// Synthetic gateway fixtures, not a live server result.
const auth = (ticket = vi.fn(async () => "fresh-ticket")) => ({ ticket, signIn: async () => {}, signOut: async () => {} });
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  delete (window as unknown as { hermesDesktop?: unknown }).hermesDesktop;
});
const bytes = () => {
  vi.stubGlobal("Blob", NodeBlob);
  vi.stubGlobal("File", NodeFile);
};

it("a picked file goes to Hermes's own file.attach with its bytes as a data URL, like Desktop's remote mode", async () => {
  bytes();
  const host = installDesktopHost({ auth: auth() });
  expect(host).not.toHaveProperty("androidMedia");
  const path = host.getPathForFile(new File([new Uint8Array([104, 105])], "note.txt", { type: "text/plain" }) as never);
  const gateway = vi.fn(async () => ({ attached: true, ref_text: '@file:"note.txt"' }) as never);
  const result = await uploadComposerAttachment({ id: "a1", kind: "file", label: "note.txt", path } as never, {
    sessionId: "runtime-1", storedSessionId: "saved-1", remote: true, requestGateway: gateway,
  });
  expect(gateway).toHaveBeenCalledExactlyOnceWith("file.attach", {
    name: "note.txt", path, session_id: "runtime-1", data_url: "data:text/plain;base64,aGk=",
  });
  expect(result).toMatchObject({ refText: '@file:"note.txt"' });
  host.dispose();
});

it("a picked image goes to Hermes's own image.attach_bytes", async () => {
  bytes();
  const host = installDesktopHost({ auth: auth() });
  const path = host.getPathForFile(new File([new Uint8Array([137, 80, 78, 71])], "shot.png", { type: "image/png" }) as never);
  const gateway = vi.fn(async () => ({ attached: true, path: "attachments/shot.png" }) as never);
  const result = await uploadComposerAttachment({ id: "i1", kind: "image", label: "shot.png", path } as never, {
    sessionId: "runtime-1", storedSessionId: "saved-1", remote: true, requestGateway: gateway,
  });
  expect(gateway).toHaveBeenCalledExactlyOnceWith("image.attach_bytes", {
    session_id: "runtime-1", content_base64: "iVBORw==", filename: "shot.png",
  });
  expect(result).toMatchObject({ path: "attachments/shot.png" });
  host.dispose();
});

it("spoken replies use Desktop's speech stream beside the chat socket, with their own fresh ticket", async () => {
  const ticket = vi.fn(async () => `ticket-${ticket.mock.calls.length}`);
  const host = installDesktopHost({ auth: auth(ticket), baseUrl: "https://gateway.example.com" });
  const url = new URL((await resolveSpeakStreamUrl({ profile: "example-profile" }))!);
  expect(url.protocol).toBe("wss:");
  expect(url.host).toBe("gateway.example.com");
  expect(url.pathname).toBe("/api/audio/speak-stream");
  expect(url.searchParams.get("ticket")).toMatch(/^ticket-/);
  expect(ticket).toHaveBeenCalledTimes(1);
  host.dispose();
});
