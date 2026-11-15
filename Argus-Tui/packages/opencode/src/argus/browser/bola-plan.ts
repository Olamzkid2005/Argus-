/**
 * The object-access verification plan (Stage 4.2).
 *
 * A BOLA/IDOR proof needs three things that cannot be invented:
 *
 *   1. two genuinely distinct, supplied identities — an owner and an accessor;
 *   2. credentials for both (password, token or cookies), never an empty shell;
 *   3. a structured discovered resource that belongs to the owner.
 *
 * The rule lives here, in `objectAccessPlan()`, so no caller can quietly fill a
 * gap: the workflow runner used to synthesize the second user as
 * `${username}_b` with the first user's password, and the verify command probed
 * a hard-coded `/api/resource`. Both are refused now, and callers surface an
 * `ObjectAccessPlanError` as an `unsupported` result instead of pretending the
 * check ran.
 */

import type { CredentialEntry } from "../engagement/credentials"

/** Where a resource URL came from. Only observed values may be verified. */
export type ObjectAccessResourceSource = "finding" | "recon" | "operator"

const DISCOVERED_SOURCES: ReadonlySet<string> = new Set<ObjectAccessResourceSource>([
  "finding",
  "recon",
  "operator",
])

export interface DiscoveredResource {
  /** Absolute http(s) URL of the resource, as observed (not templated). */
  url: string
  /** Role that owns the resource. */
  ownerRole: string
  /** Role used for the cross-user attempt. */
  accessorRole: string
  /** Value only the owner's resource should contain (record id, owner email). */
  ownerMarker?: string
  /** How the URL was learned. It must have been observed. */
  source: ObjectAccessResourceSource
  /** Reference to the observation that produced this URL. */
  evidenceRef: string
}

export interface ObjectAccessIdentity {
  role: string
  credentials: CredentialEntry
}

export interface ObjectAccessPlan {
  owner: ObjectAccessIdentity
  accessor: ObjectAccessIdentity
  resource: DiscoveredResource
}

export type ObjectAccessPlanErrorCode =
  | "missing-identity"
  | "same-identity"
  | "fabricated-identity"
  | "placeholder-identity"
  | "unstructured-resource"
  | "guessed-resource"

export class ObjectAccessPlanError extends Error {
  override readonly name = "ObjectAccessPlanError"

  constructor(
    readonly code: ObjectAccessPlanErrorCode,
    message: string,
  ) {
    super(message)
  }
}

/**
 * Values that are obviously stand-ins. A real second identity may be any
 * ordinary account, but the verifier must never be handed a placeholder and
 * then report a proof.
 */
const PLACEHOLDER_USERNAMES: ReadonlySet<string> = new Set([
  "", "user", "username", "user1", "user2", "user_a", "user_b",
  "test", "tester", "example", "changeme", "change_me",
  "victim", "attacker", "admin", "administrator", "root",
  "your_username", "your-username", "placeholder", "todo", "xxxx",
])

const PLACEHOLDER_PASSWORDS: ReadonlySet<string> = new Set([
  "", "password", "changeme", "change_me", "your_password", "placeholder", "todo", "secret",
])

function normalized(value: string | undefined): string {
  return (value ?? "").trim().toLowerCase()
}

function isPlaceholderUsername(username: string): boolean {
  const value = normalized(username)
  return PLACEHOLDER_USERNAMES.has(value) || /^(x{3,}|\.{3,})$/.test(value) || value.startsWith("your_")
}

function hasCredentials(creds: CredentialEntry): boolean {
  if (isPlaceholderUsername(creds.username)) return false
  if (creds.authToken?.trim()) return true
  if (creds.authCookies?.some((cookie) => cookie?.value?.trim())) return true
  return !PLACEHOLDER_PASSWORDS.has(normalized(creds.password))
}

/**
 * Whether `candidate` looks derived from `base` — `alice_b`, `alice-b`,
 * `alice.2`, `alice2`. A derived name is the fabricated-second-user pattern,
 * not a second person.
 */
function looksDerivedFrom(candidate: string, base: string): boolean {
  const c = normalized(candidate)
  const b = normalized(base)
  if (!c || !b || c === b) return false
  const suffixes = ["_b", "_2", "-b", "-2", ".b", ".2", "2", "1", "_alt", "-alt"]
  return suffixes.some((suffix) => c === `${b}${suffix}`)
}

function requireIdentity(
  roles: Record<string, CredentialEntry>,
  role: string,
): ObjectAccessIdentity {
  const credentials = roles[role]
  if (!credentials) {
    throw new ObjectAccessPlanError(
      "missing-identity",
      `role "${role}" is not in the credential file; supply two real identities`,
    )
  }
  if (!hasCredentials(credentials)) {
    throw new ObjectAccessPlanError(
      "placeholder-identity",
      `role "${role}" has a placeholder username/password; supply a real account`,
    )
  }
  return { role, credentials }
}

/**
 * Build the only plan an object-access check may run from.
 *
 * Throws `ObjectAccessPlanError` — never repairs the input — when identities
 * are missing, identical, derived from one another or placeholders, or when
 * the resource is not a structured, observed endpoint.
 */
export function objectAccessPlan(
  roles: Record<string, CredentialEntry>,
  resource: DiscoveredResource,
): ObjectAccessPlan {
  if (!resource || typeof resource !== "object" || typeof resource.url !== "string") {
    throw new ObjectAccessPlanError(
      "unstructured-resource",
      "the object-access resource must be a structured discovered endpoint",
    )
  }

  let parsed: URL
  try {
    parsed = new URL(resource.url)
  } catch {
    throw new ObjectAccessPlanError(
      "unstructured-resource",
      `the object-access resource URL is not absolute: ${resource.url}`,
    )
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new ObjectAccessPlanError(
      "unstructured-resource",
      `the object-access resource must be http(s), got ${parsed.protocol}`,
    )
  }

  if (!DISCOVERED_SOURCES.has(resource.source)) {
    throw new ObjectAccessPlanError(
      "guessed-resource",
      "the object-access resource must come from an observation (finding, recon or operator)",
    )
  }
  if (!resource.evidenceRef?.trim()) {
    throw new ObjectAccessPlanError(
      "guessed-resource",
      "the object-access resource has no evidence reference; a guessed URL cannot be verified",
    )
  }
  if (!resource.ownerRole?.trim() || !resource.accessorRole?.trim()) {
    throw new ObjectAccessPlanError(
      "missing-identity",
      "the object-access resource must name both the owner and the accessor role",
    )
  }
  if (resource.ownerRole === resource.accessorRole) {
    throw new ObjectAccessPlanError(
      "same-identity",
      `owner and accessor are the same role ("${resource.ownerRole}")`,
    )
  }

  const owner = requireIdentity(roles, resource.ownerRole)
  const accessor = requireIdentity(roles, resource.accessorRole)

  if (normalized(owner.credentials.username) === normalized(accessor.credentials.username)) {
    throw new ObjectAccessPlanError(
      "same-identity",
      `both roles authenticate as "${owner.credentials.username}"; a second real identity is required`,
    )
  }
  if (
    looksDerivedFrom(accessor.credentials.username, owner.credentials.username) ||
    looksDerivedFrom(owner.credentials.username, accessor.credentials.username)
  ) {
    throw new ObjectAccessPlanError(
      "fabricated-identity",
      `"${accessor.credentials.username}" looks derived from "${owner.credentials.username}"; supply a real second account`,
    )
  }

  return { owner, accessor, resource }
}

/**
 * The discovered resource for a finding, from its structured `url`.
 *
 * A finding that carries no URL has no resource to test: the description is
 * prose, and pulling a path out of it is guessing. Callers turn the throw into
 * an `unsupported` result.
 */
export function discoveredResourceForFinding(
  finding: { id: string; url?: string },
  target: string,
  roles: { ownerRole?: string; accessorRole?: string } = {},
): DiscoveredResource {
  if (!finding.url?.trim()) {
    throw new ObjectAccessPlanError(
      "unstructured-resource",
      `finding ${finding.id} carries no discovered endpoint; refusing to guess one from its description`,
    )
  }
  const absolute = new URL(finding.url, target).toString()
  return {
    url: absolute,
    ownerRole: roles.ownerRole ?? "victim",
    accessorRole: roles.accessorRole ?? "attacker",
    source: "finding",
    evidenceRef: `finding:${finding.id}`,
  }
}
