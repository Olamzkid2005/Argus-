import { afterAll, beforeAll, describe, expect, test } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { EngagementStore } from "@argus/engagement/store"
import type { EngagementCheckpoint } from "@argus/engagement/checkpoint"

let dir: string

beforeAll(() => {
  dir = mkdtempSync(join(tmpdir(), "argus-checkpoint-store-"))
})

afterAll(() => {
  try { rmSync(dir, { recursive: true, force: true }) } catch { /* best effort */ }
})

function makeCheckpoint(engagementId: string, checkpointAt: string): EngagementCheckpoint {
  return {
    engagementId,
    workflow: "assessment",
    workflowVersion: 1,
    plan: { workflow: "assessment", phases: [], errorRecovery: {}, planCreatedAt: checkpointAt },
    scope: ["https://example.com"],
    actions: [],
    actionSignatures: {},
    observations: [],
    secretRefs: ["credential:user"],
    proofStatus: {},
    budgetUsage: {
      llmCalls: 1, llmFailures: 0, inputTokens: 10, outputTokens: 2,
      costUsd: 0.01, costKnown: true, toolCalls: 1, requestCount: 1,
    },
    createdAt: "2026-11-14T10:00:00.000Z",
    startedAt: "2026-11-14T10:00:01.000Z",
    checkpointAt,
  }
}

describe("engagement checkpoint storage", () => {
  test("returns null before any checkpoint exists", () => {
    const store = new EngagementStore(join(dir, "empty.db"))
    const eng = store.createEngagement("https://example.com", "assessment")
    expect(store.getLatestCheckpoint(eng.id)).toBeNull()
    store.close()
  })

  test("round-trips the latest checkpoint for its engagement", () => {
    const store = new EngagementStore(join(dir, "roundtrip.db"))
    const eng = store.createEngagement("https://example.com", "assessment")
    const first = makeCheckpoint(eng.id, "2026-11-14T10:05:00.000Z")
    const second = makeCheckpoint(eng.id, "2026-11-14T10:06:00.000Z")
    second.budgetUsage.toolCalls = 3

    store.saveCheckpoint(first)
    store.saveCheckpoint(second)

    const loaded = store.getLatestCheckpoint(eng.id)
    expect(loaded).not.toBeNull()
    expect(loaded!.checkpointAt).toBe(second.checkpointAt)
    expect(loaded!.budgetUsage.toolCalls).toBe(3)
    expect(loaded!.secretRefs).toEqual(["credential:user"])
    expect(loaded!.plan.workflow).toBe("assessment")
    // Another engagement has no checkpoint of its own.
    const other = store.createEngagement("https://other.example", "assessment")
    expect(store.getLatestCheckpoint(other.id)).toBeNull()
    store.close()
  })
})
