/**
 * BOLA verification (Stage 4.2 items 2 and 3).
 *
 * The verifier is driven from a validated `ObjectAccessPlan`; these tests fake
 * the browser and the login module so each control and outcome can be asserted
 * exactly: public resource, failed login, invalid credentials accepted by the
 * form, owner denied their own resource, the secure twin (accessor denied), an
 * unrelated 200, and the genuine cross-user read of the owner's unique data.
 */
import { beforeEach, describe, expect, mock, test } from "bun:test"
import { BOLAVerifier } from "../../../../../src/argus/browser/verifiers/bola"
import { objectAccessPlan } from "../../../../../src/argus/browser/bola-plan"
import type { DiscoveredResource } from "../../../../../src/argus/browser/bola-plan"
import { ProofStatus } from "../../../../../src/argus/shared/types"

let rejectLoginFor: string | null = null
let acceptAnyPassword = false

mock.module("../../../../../src/argus/browser/login", () => ({
  authenticateSession: async (
    _page: unknown,
    creds: { username: string; password: string },
  ) => {
    if (acceptAnyPassword) return true
    if (rejectLoginFor && creds.username === rejectLoginFor) return false
    // The invalid-credential control appends a marker to the real password.
    return !creds.password.includes("-argus-invalid-")
  },
  isAccessDenied: (bodyText: string) => {
    const lower = bodyText.toLowerCase()
    return /\b403\b/.test(lower) || /\b401\b/.test(lower) ||
      lower.includes("forbidden") || lower.includes("access denied") ||
      lower.includes("unauthorized") || lower.includes("not authorized") ||
      lower.includes("insufficient permissions")
  },
  detectAuthChallenge: async () => null,
  logAuthChallenge: () => {},
}))

interface ResponseSpec {
  status: number
  body: string
}

const TARGET = "https://example.com"
const RESOURCE_URL = "https://example.com/api/invoices/42"

const plan = () =>
  objectAccessPlan(
    {
      victim: { username: "alice", password: "alice-real-pass" },
      attacker: { username: "mallory", password: "mallory-real-pass" },
    },
    {
      url: RESOURCE_URL,
      ownerRole: "victim",
      accessorRole: "attacker",
      source: "finding",
      evidenceRef: "finding:f-1",
    } satisfies DiscoveredResource,
  )

function makePage(spec: ResponseSpec, loginPage: ResponseSpec) {
  let current = TARGET
  return {
    goto: async (url: string) => {
      current = url
      const response = url === TARGET ? loginPage : spec
      return { status: () => response.status } as never
    },
    url: () => current,
    locator: () => ({
      innerText: async () => (current === TARGET ? loginPage.body : spec.body),
      count: async () => 1,
      first: () => ({ isVisible: async () => false, fill: async () => {}, press: async () => {}, click: async () => {} }),
      fill: async () => {},
      press: async () => {},
      click: async () => {},
    }),
    content: async () => spec.body,
    evaluate: async () => null,
    textContent: async () => spec.body,
    waitForLoadState: async () => {},
    waitForTimeout: async () => {},
    waitForSelector: async () => {},
    close: async () => {},
  }
}

/**
 * Contexts are created in a fixed order: unauthenticated baseline, invalid
 * credential control, owner, accessor.
 */
function makeEngine(opts: {
  unauthenticated?: ResponseSpec
  owner?: ResponseSpec
  accessor?: ResponseSpec
}) {
  const specs: ResponseSpec[] = [
    opts.unauthenticated ?? { status: 403, body: "Forbidden" },
    { status: 200, body: "Sign in" },
    opts.owner ?? { status: 200, body: "Invoice INV-42 for Alice" },
    opts.accessor ?? { status: 200, body: "Invoice INV-42 for Alice" },
  ]
  let index = 0
  return {
    launch: async () => {},
    close: async () => {},
    createContext: async () => {
      const spec = specs[index++] ?? { status: 200, body: "" }
      return {
        newPage: async () => makePage(spec, { status: 200, body: "Sign in" }),
        close: async () => {},
      }
    },
    captureScreenshot: async () => Buffer.from("screenshot"),
  }
}

async function runVerifier(engine: unknown) {
  const verifier = new BOLAVerifier(engine as never, TARGET, plan())
  await verifier.setup()
  await verifier.execute()
  return verifier.verify()
}

beforeEach(() => {
  rejectLoginFor = null
  acceptAnyPassword = false
})

describe("BOLAVerifier proof", () => {
  test("confirms only when the accessor receives the owner's unique data", async () => {
    const result = await runVerifier(makeEngine({}))

    expect(result.proofStatus).toBe(ProofStatus.REPRODUCED)
    expect(result.passed).toBe(true)
    expect(result.summary).toContain("BOLA confirmed")
    expect(result.summary).toContain("attacker")
  })

  test("does not confirm the secure twin that denies the accessor", async () => {
    const result = await runVerifier(
      makeEngine({ accessor: { status: 403, body: "Access denied" } }),
    )

    expect(result.proofStatus).toBe(ProofStatus.NOT_REPRODUCED)
    expect(result.passed).toBe(false)
    expect(result.summary).toContain("denied")
  })

  test("does not confirm an unrelated 200 response", async () => {
    const result = await runVerifier(
      makeEngine({ accessor: { status: 200, body: "Welcome to the public dashboard" } }),
    )

    expect(result.proofStatus).toBe(ProofStatus.INCONCLUSIVE)
    expect(result.passed).toBe(false)
    expect(result.summary).toContain("different response")
  })

  test("does not confirm a publicly accessible resource", async () => {
    const result = await runVerifier(
      makeEngine({ unauthenticated: { status: 200, body: "Invoice INV-42 for Alice" } }),
    )

    expect(result.proofStatus).toBe(ProofStatus.INCONCLUSIVE)
    expect(result.passed).toBe(false)
    expect(result.summary).toContain("without authentication")
  })

  test("is inconclusive when the owner cannot log in", async () => {
    rejectLoginFor = "alice"

    const result = await runVerifier(makeEngine({}))

    expect(result.proofStatus).toBe(ProofStatus.INCONCLUSIVE)
    expect(result.passed).toBe(false)
    expect(result.error).toMatchObject({ step: "execute", name: "LoginFailed" })
    expect(result.summary).toContain("login failed for alice")
  })

  test("is inconclusive when the login form accepts an invalid password", async () => {
    acceptAnyPassword = true

    const result = await runVerifier(makeEngine({}))

    expect(result.proofStatus).toBe(ProofStatus.INCONCLUSIVE)
    expect(result.passed).toBe(false)
    expect(result.summary).toContain("invalid password")
  })

  test("is inconclusive when the owner is denied their own resource", async () => {
    const result = await runVerifier(
      makeEngine({ owner: { status: 403, body: "Forbidden" } }),
    )

    expect(result.proofStatus).toBe(ProofStatus.INCONCLUSIVE)
    expect(result.passed).toBe(false)
    expect(result.summary).toContain("ownership was not established")
  })

  test("records every control it ran, with outcomes", async () => {
    const result = await runVerifier(makeEngine({}))

    const kinds = (result.controls ?? []).map((control) => control.kind)
    expect(kinds).toEqual([
      "unauthenticated-baseline",
      "invalid-credentials",
      "owner-resource-access",
      "accessor-resource-access",
    ])
    expect(result.controls?.find((c) => c.kind === "accessor-resource-access")?.outcome)
      .toContain("served")
  })

  test("a confirmed result carries controls so it can be promoted on proof", async () => {
    const result = await runVerifier(makeEngine({}))

    expect(result.controls?.length).toBeGreaterThan(0)
  })

  test("cleans up its browser on completion", async () => {
    let closed = false
    const engine = makeEngine({})
    const verifier = new BOLAVerifier(
      { ...engine, close: async () => { closed = true } } as never,
      TARGET,
      plan(),
    )
    await verifier.setup()
    await verifier.execute()
    await verifier.verify()
    await verifier.cleanup()

    expect(closed).toBe(true)
  })

  test("collectEvidence returns an evidence package with artifacts", async () => {
    const verifier = new BOLAVerifier(makeEngine({}) as never, TARGET, plan())
    await verifier.setup()
    await verifier.execute()
    await verifier.verify()
    const evidence = await verifier.collectEvidence()

    expect(evidence.artifacts.length).toBeGreaterThan(0)
    expect(evidence.createdAt).toBeDefined()
  })
})
