/** Credentials are memory-only. Never log or persist the returned URL. */
export function gatewayUrl(
  endpoint: string,
  token: string,
  debug = false,
): string {
  const input = endpoint.trim();
  const url = new URL(input);
  if (url.username || url.password || url.search || url.hash)
    throw new Error(
      "Use a plain gateway endpoint; put the token in its separate field.",
    );
  // Check the raw authority as well: WHATWG URL canonicalizes 127.1 / integer IP aliases.
  const rawHost = /^ws:\/\/([^/:]+)(?::[0-9]+)?(?:\/|$)/.exec(input)?.[1];
  const local =
    debug && ["localhost", "127.0.0.1", "10.0.2.2"].includes(rawHost ?? "");
  if (url.protocol !== "wss:" && !(url.protocol === "ws:" && local))
    throw new Error(
      "Use wss://. Cleartext is allowed only for explicit debug localhost / 10.0.2.2.",
    );
  if (token) url.searchParams.set("token", token);
  return url.toString();
}
