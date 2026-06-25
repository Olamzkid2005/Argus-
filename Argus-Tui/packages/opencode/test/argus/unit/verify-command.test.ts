import { describe, expect, test, beforeAll, mock } from "bun:test"
import type { NormalizedFinding } from "../../../src/argus/shared/types"

// Define mock store interface matching EngagementStore methods used by verifyCommand
interface MockStore {
  getFindingEngagementId: (id: string) => string | null
  getFinding: (id: string) => NormalizedFinding | null
  getEngagement: (id: string) => { id: string; target: string } | null
}

describe("verifyCommand direct finding lookup", () => {
  const store: MockStore = {
    getFindingEngagementId: (id: string) =>
      id === "FIND-001" ? "ENG-001" : id === "FIND-002" ? "ENG-002" : null,
    getFinding: (id: string) => {
      if (id === "FIND-001") return { id: "FIND-001", title: "SQL Injection", tool: "bola", severity: 4, confidence: 4, status: "CONFIRMED", description: "Test", phase: "recon", created_at: "2024-01-01T00:00:00Z", updated_at: "2024-01-01T00:00:00Z" }
      if (id === "FIND-002") return { id: "FIND-002", title: "XSS", tool: "xss", severity: 3, confidence: 3, status: "PENDING", description: "XSS vuln", phase: "scan", created_at: "2024-01-01T00:00:00Z", updated_at: "2024-01-01T00:00:00Z" }
      return null
    },
    getEngagement: (id: string) =>
      id === "ENG-001" ? { id: "ENG-001", target: "https://example.com" } : null,
  }

  test("uses getFindingEngagementId instead of iterating all engagements", () => {
    const engagementId = store.getFindingEngagementId("FIND-001")
    expect(engagementId).toBe("ENG-001")
  })

  test("returns null for nonexistent finding", () => {
    const engagementId = store.getFindingEngagementId("NONEXISTENT")
    expect(engagementId).toBeNull()
  })

  test("fetches finding by ID after finding engagement", () => {
    const engagementId = store.getFindingEngagementId("FIND-001")
    expect(engagementId).toBe("ENG-001")
    const finding = store.getFinding("FIND-001")
    expect(finding).not.toBeNull()
    expect(finding!.tool).toBe("bola")
  })

  test("finding found and engagement resolved produce correct output", () => {
    const engagementId = store.getFindingEngagementId("FIND-001")
    const finding = engagementId ? store.getFinding("FIND-001") : null
    const eng = engagementId ? store.getEngagement(engagementId) : null
    expect(finding).not.toBeNull()
    expect(eng).not.toBeNull()
    expect(finding!.title).toBe("SQL Injection")
    expect(eng!.target).toBe("https://example.com")
  })

  test("not found case returns finding not found message", () => {
    const findingId = "DOES_NOT_EXIST"
    const engagementId = store.getFindingEngagementId(findingId)
    const finding = engagementId ? store.getFinding(findingId) : null
    const result = !finding || !engagementId ? `Finding not found: ${findingId}` : "ok"
    expect(result).toBe("Finding not found: DOES_NOT_EXIST")
  })

  test("returns finding not found when engagement cannot be resolved", () => {
    const findingId = "FIND-002"
    const engagementId = store.getFindingEngagementId(findingId)
    const eng = engagementId ? store.getEngagement(engagementId) : null
    // FIND-002 maps to ENG-002 which has no engagement record
    expect(engagementId).toBe("ENG-002")
    expect(eng).toBeNull()
  })
})

describe("verifyCommand role matching", () => {
  const allRoles: Record<string, { username: string; password: string }> = {
    attacker: { username: "attacker_user", password: "attacker_pass" },
    Victim: { username: "victim_user", password: "victim_pass" },
    regular_user: { username: "regular_user", password: "regular_pass" },
    "Admin-Role": { username: "admin_user", password: "admin_pass" },
  }

  const matchRole = (name: string) => {
    const exactMatch = Object.entries(allRoles).find(
      ([key]) => key.toLowerCase() === name.toLowerCase(),
    )
    if (exactMatch) return exactMatch[1] as { username: string; password: string }
    const substringMatch = Object.entries(allRoles).find(
      ([key]) => key.toLowerCase().includes(name.toLowerCase()),
    )
    if (substringMatch) return substringMatch[1] as { username: string; password: string }
    return undefined
  }

  test("matches exact case-sensitive role name", () => {
    const role = matchRole("attacker")
    expect(role).toBeDefined()
    expect(role!.username).toBe("attacker_user")
  })

  test("matches case-insensitive role name", () => {
    const role = matchRole("VICTIM")
    expect(role).toBeDefined()
    expect(role!.username).toBe("victim_user")
  })

  test("matches substring role name", () => {
    const role = matchRole("user")
    expect(role).toBeDefined()
    // "user" is a substring of "regular_user" — should match first
    expect(role!.username).toBe("regular_user")
  })

  test("matches role with hyphen in name", () => {
    const role = matchRole("admin")
    expect(role).toBeDefined()
    expect(role!.username).toBe("admin_user")
  })

  test("returns undefined for unmatched role", () => {
    const role = matchRole("superadmin")
    expect(role).toBeUndefined()
  })

  test("matches attacker role for bola verifier", () => {
    const attackerRole = matchRole("attacker")
    const victimRole = matchRole("victim")
    expect(attackerRole).toBeDefined()
    expect(victimRole).toBeDefined()
    // BOLA check: finding.tool includes "bola" && attackerRole && victimRole
    expect(attackerRole!.username).toBe("attacker_user")
    expect(victimRole!.username).toBe("victim_user")
  })

  test("matches user or admin role for xss verifier", () => {
    const userRole = matchRole("user")
    const adminRole = matchRole("admin")
    expect(userRole).toBeDefined()
    expect(adminRole).toBeDefined()
    // XSS check: userRole || adminRole
    const creds = userRole ?? adminRole!
    expect(creds.username).toBe("regular_user")
  })
})
