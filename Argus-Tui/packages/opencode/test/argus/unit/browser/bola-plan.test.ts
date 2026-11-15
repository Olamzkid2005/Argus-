/**
 * The object-access plan rule (Stage 4.2 item 1).
 *
 * These are the guards that used to be caller-side improvisation: the workflow
 * runner invented `${username}_b` with the first user's password, and the
 * verify command probed a hard-coded `/api/resource`. Each test asserts the
 * specific rejection code, so removing a guard fails here rather than silently
 * producing a second "user" nobody supplied.
 */
import { describe, expect, test } from "bun:test"
import {
  ObjectAccessPlanError,
  discoveredResourceForFinding,
  objectAccessPlan,
} from "../../../../src/argus/browser/bola-plan"
import type { DiscoveredResource, ObjectAccessPlanErrorCode } from "../../../../src/argus/browser/bola-plan"
import type { CredentialEntry } from "../../../../src/argus/engagement/credentials"

const roles: Record<string, CredentialEntry> = {
  victim: { username: "alice", password: "alice-real-pass" },
  attacker: { username: "mallory", password: "mallory-real-pass" },
}

const resource: DiscoveredResource = {
  url: "https://example.com/api/invoices/42",
  ownerRole: "victim",
  accessorRole: "attacker",
  ownerMarker: "INV-42",
  source: "finding",
  evidenceRef: "finding:f-1",
}

function expectPlanError(fn: () => unknown, code: ObjectAccessPlanErrorCode): void {
  try {
    fn()
  } catch (error) {
    if (!(error instanceof ObjectAccessPlanError)) throw error
    expect(error.code).toBe(code)
    return
  }
  throw new Error(`expected ObjectAccessPlanError(${code}) but the call returned`)
}

describe("objectAccessPlan", () => {
  test("accepts two supplied, distinct identities and a discovered resource", () => {
    const plan = objectAccessPlan(roles, resource)

    expect(plan.owner.credentials.username).toBe("alice")
    expect(plan.accessor.credentials.username).toBe("mallory")
    expect(plan.resource.url).toBe("https://example.com/api/invoices/42")
  })

  test("refuses to invent a missing second identity", () => {
    expectPlanError(
      () => objectAccessPlan({ victim: roles.victim }, resource),
      "missing-identity",
    )
  })

  test("refuses the fabricated `${username}_b` account from the old runner", () => {
    const fabricated = {
      ...roles,
      attacker: { username: "alice_b", password: "alice-real-pass" },
    }

    expectPlanError(() => objectAccessPlan(fabricated, resource), "fabricated-identity")
  })

  test("refuses a derived second username with another separator", () => {
    for (const username of ["alice-b", "alice.2", "alice2"]) {
      expectPlanError(
        () => objectAccessPlan({ ...roles, attacker: { username, password: "x-real" } }, resource),
        "fabricated-identity",
      )
    }
  })

  test("refuses both roles authenticating as the same account", () => {
    expectPlanError(
      () => objectAccessPlan({ ...roles, attacker: { username: "Alice", password: "other-real" } }, resource),
      "same-identity",
    )
  })

  test("refuses a placeholder identity", () => {
    expectPlanError(
      () => objectAccessPlan({ ...roles, attacker: { username: "user", password: "real-pass" } }, resource),
      "placeholder-identity",
    )
    expectPlanError(
      () => objectAccessPlan({ ...roles, attacker: { username: "mallory", password: "changeme" } }, resource),
      "placeholder-identity",
    )
  })

  test("refuses a role that exists with no usable credential", () => {
    expectPlanError(
      () => objectAccessPlan({ ...roles, attacker: { username: "mallory", password: "" } }, resource),
      "placeholder-identity",
    )
  })

  test("accepts a token-only second identity", () => {
    const plan = objectAccessPlan(
      { ...roles, attacker: { username: "mallory", password: "", authToken: "eyJ.real.token" } },
      resource,
    )

    expect(plan.accessor.credentials.authToken).toBe("eyJ.real.token")
  })

  test("refuses a relative resource URL", () => {
    expectPlanError(
      () => objectAccessPlan(roles, { ...resource, url: "/api/invoices/42" }),
      "unstructured-resource",
    )
  })

  test("refuses a non-http(s) resource", () => {
    expectPlanError(
      () => objectAccessPlan(roles, { ...resource, url: "file:///etc/passwd" }),
      "unstructured-resource",
    )
  })

  test("refuses a resource with no observation behind it", () => {
    expectPlanError(
      () => objectAccessPlan(roles, { ...resource, evidenceRef: "" }),
      "guessed-resource",
    )
    expectPlanError(
      () => objectAccessPlan(roles, { ...resource, source: "guessed" as unknown as DiscoveredResource["source"] }),
      "guessed-resource",
    )
  })

  test("refuses one role playing both parts", () => {
    expectPlanError(
      () => objectAccessPlan(roles, { ...resource, accessorRole: "victim" }),
      "same-identity",
    )
  })
})

describe("discoveredResourceForFinding", () => {
  test("uses the finding's structured url and records its evidence", () => {
    const found = discoveredResourceForFinding(
      { id: "f-1", url: "https://example.com/api/orders/7" },
      "https://example.com",
    )

    expect(found.url).toBe("https://example.com/api/orders/7")
    expect(found.source).toBe("finding")
    expect(found.evidenceRef).toBe("finding:f-1")
  })

  test("resolves a discovered relative url against the engagement target", () => {
    const found = discoveredResourceForFinding(
      { id: "f-2", url: "/api/orders/7" },
      "https://example.com",
    )

    expect(found.url).toBe("https://example.com/api/orders/7")
  })

  test("refuses to guess a resource from the finding description", () => {
    expectPlanError(
      () => discoveredResourceForFinding({ id: "f-3" }, "https://example.com"),
      "unstructured-resource",
    )
  })
})
