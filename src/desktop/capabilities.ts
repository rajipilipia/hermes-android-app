import catalog from "./capability-contract.json";
import type { HermesApiRequest } from "../../vendor/hermes/apps/desktop/src/global";

type Schema = {
  type?: string;
  properties?: Record<string, Schema>;
  required?: string[];
  additionalProperties?: boolean;
  enum?: unknown[];
  maxLength?: number;
  pattern?: string;
  minimum?: number;
  maximum?: number;
  items?: Schema;
  maxItems?: number;
};
type Operation = {
  id: string;
  method: string;
  pathTemplate: string;
  profileQuery: boolean;
  query: Schema;
  body: Schema | null;
  pathParams: Schema;
};
const operations = catalog.operations as unknown as readonly Operation[];
const fail = (): never => {
  throw new Error(
    "This Desktop capability is unavailable or has invalid arguments on this Android connection.",
  );
};
function validate(value: unknown, schema: Schema): void {
  if (schema.type === "object") {
    if (!value || typeof value !== "object" || Array.isArray(value))
      return fail();
    const object = value as Record<string, unknown>;
    for (const key of schema.required ?? []) if (!(key in object)) fail();
    for (const [key, item] of Object.entries(object)) {
      const child = schema.properties?.[key];
      if (!child) {
        if (schema.additionalProperties === false) fail();
      } else validate(item, child);
    }
  } else if (schema.type === "array") {
    // Codex Live voice history and debug events: bounded lists of checked items.
    if (!Array.isArray(value) || value.length > (schema.maxItems ?? 0)) return fail();
    for (const item of value) validate(item, schema.items ?? { enum: [] });
  } else if (schema.type === "string") {
    if (
      typeof value !== "string" ||
      value.includes("\0") ||
      value.length > (schema.maxLength ?? 4096) ||
      (schema.pattern && !new RegExp(schema.pattern).test(value))
    )
      fail();
  } else if (schema.type === "boolean" && typeof value !== "boolean") fail();
  else if (
    schema.type === "integer" &&
    (typeof value !== "number" ||
      !Number.isSafeInteger(value) ||
      value < (schema.minimum ?? 0) ||
      value > (schema.maximum ?? 500))
  )
    fail();
  if (schema.enum && !schema.enum.includes(value)) fail();
}

export function canonicalProfile(profile?: string | null): string {
  const name = profile ?? "default";
  // Use the generated server owner grammar, including reserved names. Query
  // aggregate selectors have their own per-operation schema, never this one.
  validate(name, catalog.profileSchema);
  return name;
}

const requestFields = new Set([
  "path",
  "method",
  "body",
  "upload",
  "timeoutMs",
  "profile",
  "connectionId",
  "passive",
  "priority",
]);

export function validateCapabilityRequest(request: HermesApiRequest): void {
  if (
    !request ||
    typeof request !== "object" ||
    Array.isArray(request) ||
    Reflect.ownKeys(request).some(
      (key) => typeof key !== "string" || !requestFields.has(key),
    ) ||
    typeof request.path !== "string"
  )
    fail();
  if (
    (request.connectionId != null &&
      !["", "local", "pc"].includes(request.connectionId)) ||
    request.upload !== undefined ||
    (request.method !== undefined &&
      !["GET", "POST", "PUT", "PATCH", "DELETE"].includes(request.method)) ||
    (request.passive !== undefined && typeof request.passive !== "boolean") ||
    (request.priority !== undefined && request.priority !== "foreground") ||
    (request.timeoutMs !== undefined &&
      (!Number.isSafeInteger(request.timeoutMs) ||
        request.timeoutMs < 1 ||
        request.timeoutMs > 2147483647))
  )
    fail();
  canonicalProfile(request.profile);
}

export function capabilityCall(request: HermesApiRequest) {
  validateCapabilityRequest(request);
  const pathname = request.path.split("?", 1)[0];
  if (
    !/^\/api\/[A-Za-z0-9_/%.,:+\-]*$/.test(pathname) ||
    /(?:^|\/)\.{1,2}(?:\/|$)/.test(pathname) ||
    /%2f|%5c|%00|%2e/i.test(pathname) ||
    /[#\u0000-\u001f\u007f]/.test(request.path)
  )
    fail();
  // Desktop encodes absolute filesystem paths in typed query values. Decode
  // those once with URLSearchParams; route separators remain forbidden above.
  const url = new URL(request.path, "https://android.invalid");
  const method = request.method ?? "GET";
  let selected: Operation | undefined;
  let pathParams: Record<string, string> = {};
  for (const operation of operations) {
    if (operation.method !== method) continue;
    const keys = [...operation.pathTemplate.matchAll(/\{(\w+)\}/g)].map(
      (match) => match[1],
    );
    const expression = operation.pathTemplate
      .replace(/[.*+?^$()[\]\\]/g, "\\$&")
      .replace(/\{\w+\}/g, "([^/]+)");
    const match = new RegExp(`^${expression}$`).exec(url.pathname);
    if (!match) continue;
    selected = operation;
    pathParams = Object.fromEntries(
      keys.map((key, index) => [key, decodeURIComponent(match[index + 1])]),
    );
    break;
  }
  if (!selected) return fail();
  const profile = canonicalProfile(request.profile);
  const query: Record<string, unknown> = {};
  const seen = new Set<string>();
  for (const [key, raw] of url.searchParams) {
    if (seen.has(key)) fail();
    seen.add(key);
    // Upstream session helpers mirror their captured owner into ?profile=.
    // Only consume this redundant routing hint for declared profile-query
    // operations. It cannot select authority or change the request owner.
    // Declared aggregate selectors (including profile=all) remain typed data.
    if (
      key === "profile" &&
      selected.profileQuery &&
      !Object.hasOwn(selected.query.properties ?? {}, key)
    ) {
      if (canonicalProfile(raw) !== profile) fail();
      continue;
    }
    if (!Object.hasOwn(selected.query.properties ?? {}, key)) return fail();
    const schema = selected.query.properties?.[key];
    if (!schema) return fail();
    query[key] =
      schema.type === "boolean"
        ? raw === "true" || raw === "1"
          ? true
          : raw === "false" || raw === "0"
            ? false
            : fail()
        : schema.type === "integer"
          ? /^-?\d+$/.test(raw)
            ? Number(raw)
            : fail()
          : raw;
  }
  validate(query, selected.query);
  validate(pathParams, selected.pathParams);
  if (selected.body) validate(request.body, selected.body);
  else if (request.body != null) fail();
  return {
    operation: selected.id,
    profile,
    pathParams,
    query,
    ...(request.body === undefined ? {} : { body: request.body }),
  };
}
