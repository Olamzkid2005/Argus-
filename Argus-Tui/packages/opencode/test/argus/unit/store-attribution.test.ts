/**
 * A finding with no tool is refused by the store.
 *
 * The mission's report carried eleven anonymous LOW findings (missing
 * X-Frame-Options / HSTS). They were real, but nothing said which tool observed
 * them, so they could not be reproduced or defended. Attribution belongs at the
 * emission site; the store's job is to make sure an unattributed finding cannot
 * silently reappear if that ever regresses.
 */
import { afterAll, describe, expect, test } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { EngagementStore } from "../../../src/argus/engagement/store"
import type { NormalizedFinding } from "../../../src/argus/shared/types"

const dbDir = mkdtempSync(join(tmpdir(), "argus-attribution-test-"))
let counter = 0

function makeStore(): EngagementStore {
  counter += 1
  return new EngagementStore(join(dbDir, `attr-${counter}.db`))
}

function finding(overrides: Partial<NormalizedFinding>): NormalizedFinding {
  return {
    id: `find-${Math.random().toString(36).slice(2)}`,
    title: "Missing X-Frame-Options",
    severity: 1,
    confidence: 2,
    status: "PENDING",
    description: "The response has no X-Frame-Options header.",
    tool: "browser_security_operator",
    phase: "web_exploitation",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  }
}

afterAll(() => {
  try {
    rmSync(dbDir, { recursive: true, force: true })
  } catch {}
})

describe("store refuses unattributed findings", () => {
  test("a finding without a tool is not stored", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://example.com", "assessment")
    store.saveFindings(eng.id, [finding({ tool: "" })])
    expect(store.getFindings(eng.id)).toHaveLength(0)
  })

  test("a finding with a blank tool is not stored", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://example.com", "assessment")
    store.saveFindings(eng.id, [finding({ tool: "   " })])
    expect(store.getFindings(eng.id)).toHaveLength(0)
  })

  test("attributed findings in the same batch are still stored", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://example.com", "assessment")
    store.saveFindings(eng.id, [
      finding({ id: "kept-1", title: "Missing HSTS" }),
      finding({ id: "dropped", tool: "" }),
    ])
    const stored = store.getFindings(eng.id)
    expect(stored).toHaveLength(1)
    expect(stored[0]!.tool).toBe("browser_security_operator")
  })

  test("the refusal leaves an audit trail", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://example.com", "assessment")
    store.saveFindings(eng.id, [finding({ tool: "" })])
    const audit = store.getAuditLog(eng.id)
    expect(
      audit.some(
        (entry) =>
          entry.eventType === "FINDING_WITHOUT_TOOL" &&
          entry.message.includes("Missing X-Frame-Options"),
      ),
    ).toBe(true)
  })
})
