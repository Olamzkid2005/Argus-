import { describe, expect, test } from "bun:test"
import {
  buildCheckpoint,
  reconcileActions,
  reconcileCheckpointBudget,
  scopeIsNotWider,
  validateCheckpoint,
  type CheckpointAction,
  type CheckpointBudgetUsage,
  type EngagementCheckpoint,
} from "@argus/engagement/checkpoint"
import type { EngagementState, PhaseRecord } from "@argus/engagement/types"
import type { AssessmentPlan } from "@argus/planner/types"

const createdAt = "2026-11-14T10:00:00.000Z"
const startedAt = "2026-11-14T10:00:01.000Z"
const checkpointAt = "2026-11-14T10:05:00.000Z"

function usage(overrides: Partial<CheckpointBudgetUsage> = {}): CheckpointBudgetUsage {
  return {
    llmCalls: 4,
    llmFailures: 1,
    inputTokens: 100,
    outputTokens: 20,
    costUsd: 0.04,
    costKnown: true,
    toolCalls: 2,
    requestCount: 5,
    ...overrides,
  }
}

function engagement(overrides: Partial<EngagementState> = {}): EngagementState {
  return {
    id: "ENG-1",
    target: "https://example.com",
    workflow: "assessment",
    workflowVersion: 2,
    status: "INTERRUPTED",
    schemaVersion: 1,
    storageVersion: 2,
    version: 1,
    createdAt,
    updatedAt: checkpointAt,
    ...overrides,
  }
}

function plan(): AssessmentPlan {
  return {
    workflow: "assessment",
    phases: [],
    errorRecovery: {},
    planCreatedAt: createdAt,
  }
}

function action(overrides: Partial<CheckpointAction>): CheckpointAction {
  return {
    id: "phase-1",
    tool: "recon",
    status: "in_flight",
    readOnly: true,
    // in_flight means it had started; a phase with no start time never ran.
    startedAt,
    ...overrides,
  }
}

function checkpoint(overrides: Partial<EngagementCheckpoint> = {}): EngagementCheckpoint {
  return {
    engagementId: "ENG-1",
    workflow: "assessment",
    workflowVersion: 2,
    plan: plan(),
    scope: ["https://example.com"],
    model: "provider/model",
    limits: { maxCostUsd: 5 },
    actions: [],
    actionSignatures: {},
    observations: [],
    secretRefs: [],
    proofStatus: {},
    budgetUsage: usage(),
    createdAt,
    startedAt,
    checkpointAt,
    ...overrides,
  }
}

function options(overrides: Partial<Parameters<typeof validateCheckpoint>[1]> = {}) {
  return {
    currentWorkflowName: "assessment",
    currentWorkflowVersion: 2,
    currentScope: ["https://example.com"],
    ...overrides,
  }
}

describe("validateCheckpoint", () => {
  test("accepts an ordered, compatible checkpoint", () => {
    const result = validateCheckpoint(checkpoint(), options())
    expect(result.ok).toBe(true)
    expect(result.reasons).toEqual([])
  })

  test("rejects missing explicit timestamps instead of inferring progress", () => {
    const result = validateCheckpoint(checkpoint({ createdAt: "" }), options())
    expect(result.ok).toBe(false)
    expect(result.reasons.join(" ")).toContain("missing createdAt")
  })

  test("rejects a timestamp without an explicit UTC offset", () => {
    const result = validateCheckpoint(
      checkpoint({ checkpointAt: "2026-11-14 10:05:00" }),
      options(),
    )
    expect(result.ok).toBe(false)
    expect(result.reasons.join(" ")).toContain("explicit UTC")
  })

  test("rejects out-of-order timestamps", () => {
    const result = validateCheckpoint(
      checkpoint({ startedAt: "2026-11-14T09:00:00.000Z" }),
      options(),
    )
    expect(result.ok).toBe(false)
    expect(result.reasons.join(" ")).toContain("startedAt precedes createdAt")
  })

  test("rejects a different workflow name or version", () => {
    const result = validateCheckpoint(
      checkpoint(),
      options({ currentWorkflowName: "other", currentWorkflowVersion: 3 }),
    )
    expect(result.ok).toBe(false)
    expect(result.reasons.join(" ")).toContain("workflow mismatch")
    expect(result.reasons.join(" ")).toContain("workflow version mismatch")
  })

  test("rejects a checkpoint whose scope is wider than the current scope", () => {
    const result = validateCheckpoint(
      checkpoint({ scope: ["https://example.com", "https://other.example"] }),
      options(),
    )
    expect(result.ok).toBe(false)
    expect(result.reasons.join(" ")).toContain("wider")
  })

  test("rejects a checkpoint with no approved plan", () => {
    const result = validateCheckpoint(
      checkpoint({ plan: undefined as unknown as AssessmentPlan }),
      options(),
    )
    expect(result.ok).toBe(false)
    expect(result.reasons.join(" ")).toContain("no approved plan")
  })

  test("rejects a checkpoint whose deadline has passed", () => {
    const result = validateCheckpoint(
      checkpoint({
        budgetUsage: usage({ deadlineAt: "2026-11-14T10:04:00.000Z" }),
      }),
      options({ now: new Date("2026-11-14T11:00:00.000Z") }),
    )
    expect(result.ok).toBe(false)
    expect(result.reasons.join(" ")).toContain("deadline")
  })
})

describe("checkpoint provenance and budget reconciliation", () => {
  test("carries action reasons, provenance, auth identities, and worker budget", () => {
    const cp = buildCheckpoint({
      engagement: engagement(),
      plan: plan(),
      phases: [{
        id: "phase-1",
        engagementId: "ENG-1",
        name: "recon",
        status: "COMPLETED",
        capabilities: [],
        executionMode: "sequential",
        replanCycle: false,
      }],
      scope: ["https://example.com"],
      secretRefs: ["credential:attacker"],
      authIdentities: ["credential:attacker", "worker:attacker"],
      budgetUsage: usage({ toolCalls: 3 }),
      workerBudget: { toolCalls: 2, executedTools: ["nuclei"], identities: ["attacker"], sessions: 1 },
      startedAt,
      actionDetails: {
        "phase-1": {
          reason: "approved recon capability",
          source: "plan",
          by: "local-operator",
          provenance: {
            source: "plan",
            reason: "approved recon capability",
            by: "local-operator",
            actions: [{ tool: "nuclei", outcome: "succeeded-empty", reasoning: "engine choice", identity: "attacker", source: "llm" }],
          },
        },
      },
    })
    expect(cp.actions[0].reason).toBe("approved recon capability")
    expect(cp.actions[0].provenance?.actions?.[0].identity).toBe("attacker")
    expect(cp.authIdentities).toEqual(["credential:attacker", "worker:attacker"])
    expect(validateCheckpoint(cp, options()).ok).toBe(true)
    const reconciled = reconcileCheckpointBudget(cp.budgetUsage, cp.workerBudget)
    expect(reconciled.source).toBe("merged (ts driver + worker agent sessions)")
    expect(reconciled.toolCalls).toBe(3)
    expect(reconciled.discrepancies.join(" ")).toContain("worker sessions recorded 2 tool call(s); TS driver recorded 3")
  })

  test("rejects malformed auth identities and worker ledgers", () => {
    const badIdentities = validateCheckpoint(checkpoint({ authIdentities: [""] }), options())
    expect(badIdentities.ok).toBe(false)
    expect(badIdentities.reasons.join(" ")).toContain("auth identities")
    const unscopedIdentities = validateCheckpoint(checkpoint({ authIdentities: ["attacker"] }), options())
    expect(unscopedIdentities.ok).toBe(false)
    expect(unscopedIdentities.reasons.join(" ")).toContain("auth identities")
    const badWorker = validateCheckpoint(checkpoint({ workerBudget: { toolCalls: -1, executedTools: [], identities: [], sessions: 0 } }), options())
    expect(badWorker.ok).toBe(false)
    expect(badWorker.reasons.join(" ")).toContain("worker budget ledger")
  })

  test("a checkpoint without worker evidence stays an explicit local estimate", () => {
    const reconciled = reconcileCheckpointBudget(usage({ toolCalls: 1 }), undefined)
    expect(reconciled).toEqual({
      source: "local-estimate",
      toolCalls: 1,
      discrepancies: ["no worker session ledger was attached to this checkpoint"],
    })
  })
})

describe("reconcileActions", () => {
  test("completed actions are never replayed", () => {
    const result = reconcileActions([action({ status: "succeeded" })])
    expect(result.completedActionIds).toEqual(["phase-1"])
    expect(result.retryActionIds).toEqual([])
    expect(result.blockedActionIds).toEqual([])
  })

  test("an interrupted read-only action may be retried", () => {
    const result = reconcileActions([action({ readOnly: true })])
    expect(result.retryActionIds).toEqual(["phase-1"])
    expect(result.blockedActionIds).toEqual([])
  })

  test("an interrupted state-changing action is ambiguous and blocks resume", () => {
    const result = reconcileActions([action({ readOnly: false, tool: "sqlmap" })])
    expect(result.blockedActionIds).toEqual(["phase-1"])
    expect(result.retryActionIds).toEqual([])
  })

  test("failed and skipped actions are not silently replayed", () => {
    const result = reconcileActions([
      action({ id: "a", status: "failed", readOnly: true }),
      action({ id: "b", status: "skipped" }),
    ])
    expect(result.completedActionIds).toEqual([])
    expect(result.retryActionIds).toEqual([])
    expect(result.blockedActionIds).toEqual([])
  })
})

describe("scopeIsNotWider", () => {
  test("trailing slashes and case do not widen scope", () => {
    expect(scopeIsNotWider(["HTTPS://Example.com/"], ["https://example.com"])).toBe(true)
  })

  test("an empty current scope cannot authorize a stored scope", () => {
    expect(scopeIsNotWider(["https://example.com"], [])).toBe(false)
  })
})

describe("buildCheckpoint", () => {
  function phase(overrides: Partial<PhaseRecord>): PhaseRecord {
    return {
      id: "phase-1",
      engagementId: "ENG-1",
      name: "recon",
      status: "COMPLETED",
      capabilities: [],
      executionMode: "sequential",
      replanCycle: false,
      ...overrides,
    }
  }

  test("maps phase results into actions with explicit timestamps", () => {
    const cp = buildCheckpoint({
      engagement: engagement(),
      plan: plan(),
      phases: [
        phase({ id: "p1", status: "COMPLETED", startedAt, completedAt: checkpointAt }),
        phase({ id: "p2", name: "sqlmap", status: "RUNNING", startedAt }),
        phase({ id: "p3", status: "FAILED", error: "boom" }),
        phase({ id: "p4", name: "web_exploitation", status: "RUNNING", startedAt }),
      ],
      scope: ["https://example.com"],
      budgetUsage: usage(),
      startedAt,
      now: new Date(checkpointAt),
    })

    expect(cp.createdAt).toBe(createdAt)
    expect(cp.checkpointAt).toBe(checkpointAt)
    expect(cp.actions.map((a) => a.status)).toEqual([
      "succeeded",
      "in_flight",
      "failed",
      "in_flight",
    ])
    // Scanning is replayable; exploitation is state-changing and must not be.
    expect(cp.actions[0].readOnly).toBe(true)
    expect(cp.actions[1].readOnly).toBe(true)
    expect(cp.actions[3].readOnly).toBe(false)
    expect(cp.actionSignatures[cp.actions[0].id]).toBe("recon:")
    expect(cp.actions[0].startedAt).toBe(startedAt)
    expect(cp.actions[2].error).toBe("boom")
    expect(cp.budgetUsage.toolCalls).toBe(2)
  })

  test("persists secret references, never secret values", () => {
    const cp = buildCheckpoint({
      engagement: engagement(),
      plan: plan(),
      phases: [],
      scope: ["https://example.com"],
      secretRefs: ["credential:user"],
      budgetUsage: usage(),
      startedAt,
    })
    expect(cp.secretRefs).toEqual(["credential:user"])
    expect(JSON.stringify(cp)).not.toContain("password")
  })
})

describe("checkpoint: phases that never started are not in flight", () => {
  const engagement = {
    id: "eng-1",
    target: "https://example.com",
    workflow: "full_assessment",
    workflowVersion: 1,
    status: "INTERRUPTED" as const,
    schemaVersion: 1,
    storageVersion: 2,
    version: 1,
    createdAt: "2026-11-16T08:00:00.000Z",
    updatedAt: "2026-11-16T08:00:00.000Z",
  }

  function checkpointWith(phases: PhaseRecord[]) {
    return buildCheckpoint({
      engagement: engagement as never,
      plan: { workflow: "full_assessment", phases: [], errorRecovery: {}, planCreatedAt: engagement.createdAt } as never,
      phases,
      scope: ["https://example.com"],
      budgetUsage: {
        llmCalls: 0, llmFailures: 0, inputTokens: 0, outputTokens: 0,
        costUsd: 0, costKnown: true, toolCalls: 1, requestCount: 0,
      },
    })
  }

  test("a PENDING state-changing phase does not block resume", () => {
    const cp = checkpointWith([
      {
        id: "phase-scan", engagementId: "eng-1", name: "vuln_scan", status: "RUNNING",
        capabilities: [], executionMode: "sequential", replanCycle: false,
        startedAt: "2026-11-16T08:00:05.000Z",
      },
      {
        id: "phase-exploit", engagementId: "eng-1", name: "web_exploitation", status: "PENDING",
        capabilities: [], executionMode: "sequential", replanCycle: false,
      },
    ])
    const reconciled = reconcileActions(cp.actions)
    expect(reconciled.blockedActionIds).toEqual([])
    // The read-only phase that was actually running is retried.
    expect(reconciled.retryActionIds).toEqual(["phase-scan"])
  })

  test("a state-changing phase that had started still pauses for a decision", () => {
    const cp = checkpointWith([
      {
        id: "phase-exploit", engagementId: "eng-1", name: "web_exploitation", status: "RUNNING",
        capabilities: [], executionMode: "sequential", replanCycle: false,
        startedAt: "2026-11-16T08:00:05.000Z",
      },
    ])
    expect(reconcileActions(cp.actions).blockedActionIds).toEqual(["phase-exploit"])
  })
})
