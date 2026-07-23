import { afterAll, describe, expect, test } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { EngagementStore } from "../../../src/argus/engagement/store"
import type { NormalizedFinding } from "../../../src/argus/shared/types"

let dbDir: string
const stores: EngagementStore[] = []

afterAll(() => {
  for (const s of stores) {
    try { s.close() } catch { /* best-effort */ }
  }
  stores.length = 0
  if (dbDir) {
    // Retry rmSync with backoff to handle transient EBUSY on Windows.
    // After close(), SQLite WAL checkpoint + antivirus may briefly hold
    // file handles. This matches the retry pattern in EngagementStore.
    for (let attempt = 1; attempt <= 5; attempt++) {
      try {
        rmSync(dbDir, { recursive: true, force: true })
        break
      } catch (err) {
        if (attempt < 5) {
          // Synchronous busy-wait backoff (same as store.ts)
          const deadline = Date.now() + 100 * Math.pow(2, attempt - 1)
          while (Date.now() < deadline) { /* busy-wait */ }
        } else {
          console.warn(`Failed to remove temp dir ${dbDir}:`, (err as Error).message)
        }
      }
    }
  }
})

function makeStore(): EngagementStore {
  if (!dbDir) dbDir = mkdtempSync(join(tmpdir(), "argus-finding-lookup-"))
  const store = new EngagementStore(join(dbDir, `test-${Date.now()}-${Math.random().toString(36).slice(2, 6)}.db`))
  stores.push(store)
  return store
}

function makeFinding(overrides?: Partial<NormalizedFinding>): NormalizedFinding {
  return {
    id: `find-${crypto.randomUUID()}`,
    title: "test finding",
    severity: 2,
    confidence: 2,
    status: "PENDING",
    description: "test",
    tool: "nuclei",
    phase: "recon",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  }
}

describe("EngagementStore getFindingEngagementId", () => {
  test("returns correct engagement ID for a finding", () => {
    const store = makeStore()
    const eng1 = store.createEngagement("https://example.com", "assessment")
    const eng2 = store.createEngagement("https://test.com", "quick")

    const finding = makeFinding()
    store.saveFindings(eng1.id, [finding])

    const result = store.getFindingEngagementId(finding.id)
    expect(result).toBe(eng1.id)
    expect(result).not.toBe(eng2.id)
  })

  test("returns correct engagement when multiple engagements have findings", () => {
    const store = makeStore()
    const eng1 = store.createEngagement("https://alpha.com", "full")
    const eng2 = store.createEngagement("https://beta.com", "quick")

    const finding1 = makeFinding({ id: "find-alpha-1", title: "alpha finding" })
    const finding2 = makeFinding({ id: "find-beta-1", title: "beta finding" })

    store.saveFindings(eng1.id, [finding1])
    store.saveFindings(eng2.id, [finding2])

    expect(store.getFindingEngagementId("find-alpha-1")).toBe(eng1.id)
    expect(store.getFindingEngagementId("find-beta-1")).toBe(eng2.id)
  })

  test("returns null for nonexistent finding", () => {
    const store = makeStore()
    const result = store.getFindingEngagementId("nonexistent-finding-id")
    expect(result).toBeNull()
  })

  test("returns null for finding ID from a different engagement after finding is saved", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://example.com", "assessment")
    const finding = makeFinding()
    store.saveFindings(eng.id, [finding])

    expect(store.getFindingEngagementId("wrong-id")).toBeNull()
  })

  test("returns null when no engagements exist", () => {
    const store = makeStore()
    expect(store.getFindingEngagementId("any-id")).toBeNull()
  })

  test("lookup still works after engagement is deleted (finding row still exists)", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://example.com", "assessment")
    const finding = makeFinding()
    store.saveFindings(eng.id, [finding])

    const engId = store.getFindingEngagementId(finding.id)
    expect(engId).toBe(eng.id)
  })
})
