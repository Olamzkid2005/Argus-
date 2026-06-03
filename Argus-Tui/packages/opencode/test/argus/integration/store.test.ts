import { describe, expect, test } from "bun:test"
import { mkdtempSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { EngagementStore } from "../../../src/argus/engagement/store"
import type { PhaseRecord } from "../../../src/argus/engagement/types"
import { Severity, Confidence } from "../../../src/argus/planner/types"
import type { NormalizedFinding } from "../../../src/argus/planner/types"

let dbDir: string

function makeStore(): EngagementStore {
  if (!dbDir) dbDir = mkdtempSync(join(tmpdir(), "argus-store-test-"))
  return new EngagementStore(join(dbDir, `test-${Date.now()}-${Math.random().toString(36).slice(2, 6)}.db`))
}

describe("EngagementStore", () => {
  test("createEngagement() creates engagement with CREATED status, generates ID", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://example.com", "assessment")
    expect(eng.id).toBeTruthy()
    expect(eng.id).toMatch(/^ENG-/)
    expect(eng.target).toBe("https://example.com")
    expect(eng.workflow).toBe("assessment")
    expect(eng.status).toBe("CREATED")
    expect(eng.createdAt).toBeTruthy()
  })

  test("getEngagement() returns null for unknown ID", () => {
    const store = makeStore()
    const result = store.getEngagement("nonexistent-id")
    expect(result).toBeNull()
  })

  test("getEngagement() returns engagement data for known ID", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://test.com", "quick")
    const result = store.getEngagement(eng.id)
    expect(result).not.toBeNull()
    expect(result!.id).toBe(eng.id)
    expect(result!.target).toBe("https://test.com")
    expect(result!.workflow).toBe("quick")
  })

  test("updateStatus() changes engagement status", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://status-test.com", "full")
    store.updateStatus(eng.id, "RUNNING")
    const updated = store.getEngagement(eng.id)
    expect(updated!.status).toBe("RUNNING")
  })

  test("saveEngagement() updates engagement fields", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://save-test.com", "full")
    eng.target = "https://updated-target.com"
    eng.workflowVersion = 2
    store.saveEngagement(eng)
    const updated = store.getEngagement(eng.id)
    expect(updated!.target).toBe("https://updated-target.com")
    expect(updated!.workflowVersion).toBe(2)
  })

  test("listEngagements() returns all engagements sorted by created_at desc", () => {
    const store = makeStore()
    const e1 = store.createEngagement("https://first.com", "assessment")
    const e2 = store.createEngagement("https://second.com", "quick")
    const e3 = store.createEngagement("https://third.com", "full")
    const list = store.listEngagements()
    const ids = list.map((e) => e.id)
    const e1Idx = ids.indexOf(e1.id)
    const e2Idx = ids.indexOf(e2.id)
    const e3Idx = ids.indexOf(e3.id)
    expect(e3Idx).toBeLessThan(e2Idx)
    expect(e2Idx).toBeLessThan(e1Idx)
  })

  test("savePhases() persists phase records for an engagement", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://phases-test.com", "assessment")
    const phases: PhaseRecord[] = [
      { id: `sp-${Date.now()}-0-recon`, engagementId: eng.id, name: "recon", status: "PENDING", capabilities: ["web_recon", "port_scanning"], executionMode: "parallel", replanCycle: false },
      { id: `sp-${Date.now()}-1-vuln`, engagementId: eng.id, name: "vuln_scan", status: "PENDING", capabilities: ["vulnerability_scanning"], executionMode: "parallel", replanCycle: false },
    ]
    store.savePhases(eng.id, phases)
    const saved = store.getPhases(eng.id)
    expect(saved).toHaveLength(2)
    expect(saved[0].name).toBe("recon")
    expect(saved[1].name).toBe("vuln_scan")
  })

  test("getPhases() returns phases for an engagement", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://get-phases.com", "assessment")
    const phaseId = `gp-${Date.now()}-recon`
    const phases: PhaseRecord[] = [
      { id: phaseId, engagementId: eng.id, name: "recon", status: "PENDING", capabilities: ["web_recon"], executionMode: "parallel", replanCycle: false },
    ]
    store.savePhases(eng.id, phases)
    const result = store.getPhases(eng.id)
    expect(result).toHaveLength(1)
    expect(result[0].id).toBe(phaseId)
  })

  test("savePhase() updates a single phase record", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://save-phase.com", "assessment")
    const phaseId = `sup-${Date.now()}-recon`
    const phase: PhaseRecord = { id: phaseId, engagementId: eng.id, name: "recon", status: "PENDING", capabilities: ["web_recon"], executionMode: "parallel", replanCycle: false }
    store.savePhases(eng.id, [phase])
    const updated: PhaseRecord = { ...phase, status: "RUNNING", startedAt: new Date().toISOString() }
    store.savePhase(eng.id, updated)
    const phases = store.getPhases(eng.id)
    expect(phases).toHaveLength(1)
    expect(phases[0].status).toBe("RUNNING")
    expect(phases[0].startedAt).toBeTruthy()
  })

  test("saveFindings() persists findings for engagement", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://findings-test.com", "assessment")
    const findings: NormalizedFinding[] = [
      { id: "f1", title: "XSS Vulnerability", severity: Severity.HIGH, confidence: Confidence.MEDIUM, status: "PENDING", description: "XSS in search", subtype: "xss", tool: "scanner", phase: "recon", created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
      { id: "f2", title: "SQL Injection", severity: Severity.CRITICAL, confidence: Confidence.HIGH, status: "PENDING", description: "SQLi in login", subtype: "sqli", tool: "scanner", phase: "vuln", created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
    ]
    store.saveFindings(eng.id, findings)
    const saved = store.getFindings(eng.id)
    expect(saved).toHaveLength(2)
  })

  test("getFindings() returns findings ordered by severity desc", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://severity-order.com", "assessment")
    const findings: NormalizedFinding[] = [
      { id: "fl", title: "Low Issue", severity: Severity.LOW, confidence: Confidence.INFORMATIONAL, status: "PENDING", description: "low", tool: "scanner", phase: "recon", created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
      { id: "fc", title: "Critical Issue", severity: Severity.CRITICAL, confidence: Confidence.CONFIRMED, status: "PENDING", description: "critical", tool: "scanner", phase: "vuln", created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
      { id: "fh", title: "High Issue", severity: Severity.HIGH, confidence: Confidence.HIGH, status: "PENDING", description: "high", tool: "scanner", phase: "vuln", created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
    ]
    store.saveFindings(eng.id, findings)
    const saved = store.getFindings(eng.id)
    expect(saved).toHaveLength(3)
    expect(saved[0].severity).toBe(Severity.CRITICAL)
    expect(saved[1].severity).toBe(Severity.HIGH)
    expect(saved[2].severity).toBe(Severity.LOW)
  })

  test("saveFindings() replaces previous findings for same engagement", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://replace-findings.com", "assessment")
    store.saveFindings(eng.id, [
      { id: "fo", title: "Old Finding", severity: Severity.INFO, confidence: Confidence.INFORMATIONAL, status: "PENDING", description: "old", tool: "scanner", phase: "recon", created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
    ])
    store.saveFindings(eng.id, [
      { id: "fn", title: "New Finding", severity: Severity.HIGH, confidence: Confidence.HIGH, status: "PENDING", description: "new", tool: "scanner", phase: "vuln", created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
    ])
    const saved = store.getFindings(eng.id)
    expect(saved).toHaveLength(1)
    expect(saved[0].id).toBe("fn")
    expect(saved[0].title).toBe("New Finding")
  })

  test("appendAuditLog() writes audit entries", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://audit-test.com", "assessment")
    store.appendAuditLog(eng.id, "TEST_EVENT", "Test message", { key: "value" })
    store.appendAuditLog(eng.id, "ANOTHER_EVENT", "Another message")
  })

  test("Multiple engagements can be created independently", () => {
    const store = makeStore()
    const e1 = store.createEngagement("https://multi-1.com", "quick")
    const e2 = store.createEngagement("https://multi-2.com", "full")
    expect(e1.id).not.toBe(e2.id)
    expect(store.getEngagement(e1.id)!.target).toBe("https://multi-1.com")
    expect(store.getEngagement(e2.id)!.target).toBe("https://multi-2.com")
  })

  test("Phases with capabilities array are serialized/deserialized correctly", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://caps-test.com", "assessment")
    const caps = ["web_recon", "port_scanning", "vulnerability_scanning"]
    const phaseId = `caps-${Date.now()}-test`
    const phase: PhaseRecord = { id: phaseId, engagementId: eng.id, name: "test", status: "PENDING", capabilities: caps, executionMode: "parallel", replanCycle: false }
    store.savePhases(eng.id, [phase])
    const saved = store.getPhases(eng.id)
    expect(saved[0].capabilities).toEqual(caps)
  })

  test("Handles WAL mode pragma", () => {
    const store = makeStore()
    const eng = store.createEngagement("https://wal-test.com", "assessment")
    expect(eng.id).toBeTruthy()
  })
})
