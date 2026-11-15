/**
 * Shared derivation for executable action provenance.
 *
 * Hybrid actions arrive with free-form `provenance` labels and arbitrary
 * argument maps. Reports must distinguish engine-chosen actions from planned
 * or fallback actions without ever retaining credential values. These helpers
 * normalize the source label and extract only non-secret identity labels.
 */

export type HybridActionSource = "llm" | "deterministic" | "fallback";

const IDENTITY_KEYS = new Set(["identity", "email", "username", "user", "role"]);

/** Map a worker/driver provenance label onto the report vocabulary. */
export function normalizeActionSource(source: unknown): HybridActionSource {
  if (source === "llm") return "llm";
  if (source === "fallback") return "fallback";
  return "deterministic";
}

/**
 * Extract a non-secret identity label from action arguments.
 *
 * Only whitelisted identity keys are considered. Passwords, tokens, cookies,
 * session values, and authorization material are never treated as identity
 * metadata, even when an argument map nests them under an identity key.
 */
export function identityFromActionArguments(args: unknown): string {
  if (!args || typeof args !== "object" || Array.isArray(args)) return "";
  const record = args as Record<string, unknown>;
  for (const [key, value] of Object.entries(record)) {
    if (typeof value !== "string" || value.trim().length === 0) continue;
    const normalized = key.toLowerCase();
    if (!IDENTITY_KEYS.has(normalized)) continue;
    if (/(password|passwd|secret|token|cookie|session|auth|key)/.test(normalized)) continue;
    return value;
  }
  return "";
}

/** Provenance detail carried on one executed hybrid action. */
export interface ActionProvenanceDetail {
  reasoning?: string;
  identity?: string;
  source: HybridActionSource;
}

/** Attach worker reasoning, identity, and normalized provenance to an action. */
export function provenanceForAction(params: {
  reasoning?: unknown;
  args?: unknown;
  provenance?: unknown;
}): ActionProvenanceDetail {
  const reasoning = typeof params.reasoning === "string" && params.reasoning.length > 0
    ? params.reasoning
    : undefined;
  const identity = identityFromActionArguments(params.args);
  return {
    ...(reasoning === undefined ? {} : { reasoning }),
    ...(identity === "" ? {} : { identity }),
    source: normalizeActionSource(params.provenance),
  };
}
