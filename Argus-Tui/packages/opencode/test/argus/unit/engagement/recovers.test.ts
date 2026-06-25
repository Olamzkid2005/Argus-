import { describe, expect, test } from "bun:test"
import { validateWorkflowVersion, canResume, canRetryPhase } from "@argus/engagement/recovery"
import type { EngagementState } from "@argus/engagement/types"

function makeEngagement(overrides?: Partial<EngagementState>): EngagementState {
  return {
    id: "eng-1",
    target: "https://example.com",
    workflow: "test-workflow",
    workflowVersion: 1,
    status: "CREATED",
    schemaVersion: 1,
    storageVersion: 2,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    ...overrides,
  }
}

describe("validateWorkflowVersion", () => {
  test("returns true when versions match", () => {
    const eng = makeEngagement({ workflowVersion: 3 })
    expect(validateWorkflowVersion(eng, 3)).toBe(true)
  })

  test("returns false when versions differ", () => {
    const eng = makeEngagement({ workflowVersion: 2 })
    expect(validateWorkflowVersion(eng, 5)).toBe(false)
  })
})

describe("canResume", () => {
  test("returns true for RUNNING", () => {
    expect(canResume(makeEngagement({ status: "RUNNING" }))).toBe(true)
  })

  test("returns true for PAUSED", () => {
    expect(canResume(makeEngagement({ status: "PAUSED" }))).toBe(true)
  })

  test("returns false for CREATED", () => {
    expect(canResume(makeEngagement({ status: "CREATED" }))).toBe(false)
  })

  test("returns false for COMPLETED", () => {
    expect(canResume(makeEngagement({ status: "COMPLETED" }))).toBe(false)
  })

  test("returns false for FAILED", () => {
    expect(canResume(makeEngagement({ status: "FAILED" }))).toBe(false)
  })
})

describe("canRetryPhase", () => {
  test("returns true for FAILED", () => {
    expect(canRetryPhase("FAILED")).toBe(true)
  })

  test("returns true for SKIPPED", () => {
    expect(canRetryPhase("SKIPPED")).toBe(true)
  })

  test("returns false for PENDING", () => {
    expect(canRetryPhase("PENDING")).toBe(false)
  })

  test("returns false for RUNNING", () => {
    expect(canRetryPhase("RUNNING")).toBe(false)
  })

  test("returns false for COMPLETED", () => {
    expect(canRetryPhase("COMPLETED")).toBe(false)
  })
})
