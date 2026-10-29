// Android build adapter: the phone talks to exactly one Hermes server, so an owner route tagged with the
// explicit `local` source is that server. Desktop keeps `conn:local::<profile>` as a separate registry route
// and dials it through Electron's getConnectionFor; the phone has no such door, so every request for an
// existing chat owned by `local` (for example a second Codex Live task in the same chat) threw "This Desktop
// build cannot dial registry connections" before anything was sent. Here `local` keys like a null source
// (the same rule Desktop's own backendScopeKey uses), so those requests take the profile route on the one
// server. Other source ids are unchanged. Vendor bytes stay unchanged; the exact-match guard fails the build
// if the Desktop source moves.
function replaceOnce(code: string, before: string, after: string, label: string): string {
  if (code.split(before).length !== 2) throw new Error(`Android ${label} adapter: pinned Desktop source changed.`);
  return code.replace(before, after);
}

export function patchPhoneConnectionScope(id: string, source: string): string | undefined {
  const file = id.replaceAll("\\", "/").split("?")[0];
  if (!file.endsWith("/vendor/hermes/apps/shared/src/backend-scope.ts")) return undefined;
  return replaceOnce(source, "  return connection ? `conn:${connection}::${profileKey}` : profileKey\n",
    "  // Android: one server; its explicit `local` source is that server, not a registry door.\n" +
    "  return connection && connection !== LOCAL_CONNECTION_ID ? `conn:${connection}::${profileKey}` : profileKey\n",
    "phone connection scope");
}
