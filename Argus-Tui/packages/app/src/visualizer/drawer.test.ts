/**
 * Tests for AttackDetailDrawer — slide-in panel for finding and chain details.
 *
 * Focuses on the new exploit script and verification status sections:
 *   - renderExploitScriptSection() — script text, steps, impact
 *   - renderVerificationSection() — verified/unverified badges, confidence, reason
 *   - openChain() — full chain drawer rendering
 *   - openFinding() — finding drawer with chain context
 *   - open() / close() — panel visibility
 *   - Escape key — closes drawer
 *   - Edge cases — missing data, string vs object scripts, empty arrays
 */

import { beforeEach, describe, expect, test } from "bun:test"
import { AttackDetailDrawer } from "./drawer"
import type { AttackPathData, GraphNodeData } from "./index"

// ──────────────────────────────────────────────
//  Fixtures
// ──────────────────────────────────────────────

const SAMPLE_FINDING: GraphNodeData = {
  id: "finding_001",
  type: "vulnerability",
  data: {
    type: "XSS",
    severity: "HIGH",
    endpoint: "/search",
  },
  cvss: 7.5,
  confidence: 0.92,
  prerequisites: ["User must be logged in"],
  downstream_impacts: ["Session theft", "Account takeover"],
}

const SAMPLE_CHAIN: AttackPathData = {
  risk_score: 8.5,
  chain_id: "chain_001",
  chain_name: "XSS → CSRF → ATO",
  nodes: [
    {
      id: "vuln_001",
      type: "vulnerability",
      data: { type: "XSS", severity: "HIGH", endpoint: "/search" },
      cvss: 7.5,
      confidence: 0.9,
      prerequisites: [],
      downstream_impacts: [],
    },
    {
      id: "vuln_002",
      type: "vulnerability",
      data: { type: "CSRF", severity: "MEDIUM", endpoint: "/account/update" },
      cvss: 5.0,
      confidence: 0.8,
      prerequisites: [],
      downstream_impacts: [],
    },
  ],
  edges: [
    {
      from_node: "vuln_001",
      to_node: "vuln_002",
      type: "chain",
      correlation_factor: 1.4,
      relationship_type: "enables",
    },
  ],
}

const CHAIN_EXPLOIT_SCRIPT = {
  script: "#!/bin/bash\n# XSS → CSRF → ATO chain\ncurl -X POST 'https://target.com/search' -d '<script>fetch(\"/api/token\")</script>'",
  steps: [
    { summary: "Inject XSS payload at /search endpoint" },
    { summary: "Steal CSRF token from DOM via XSS" },
    { summary: "Perform authenticated account takeover using stolen token" },
  ],
  impact_summary: "Full account takeover of any victim visiting the /search page while logged in.",
  chain_name: "XSS → CSRF → ATO",
  generated_at: "2026-07-30T12:00:00Z",
  _warning: "FOR AUTHORIZED SECURITY TESTING ONLY.",
}

const CHAIN_WITH_VERIFICATION: AttackPathData = {
  ...SAMPLE_CHAIN,
  chain_exploit_script: CHAIN_EXPLOIT_SCRIPT,
  verification: {
    verified: true,
    confidence: "high",
    reason: "All 3 exploit steps executed successfully in sandbox against test environment.",
  },
}

const CHAIN_WITHOUT_VERIFICATION: AttackPathData = {
  ...SAMPLE_CHAIN,
  chain_exploit_script: CHAIN_EXPLOIT_SCRIPT,
}

const CHAIN_WITH_STRING_SCRIPT: AttackPathData = {
  ...SAMPLE_CHAIN,
  chain_exploit_script: "#!/bin/bash\necho 'simple script'",
}

const CHAIN_FAILED_VERIFICATION: AttackPathData = {
  ...SAMPLE_CHAIN,
  chain_exploit_script: CHAIN_EXPLOIT_SCRIPT,
  verification: {
    verified: false,
    confidence: "low",
    reason: "Network connection to target failed — sandbox could not reach 10.0.0.1:443",
  },
}

// ──────────────────────────────────────────────
//  Helpers
// ──────────────────────────────────────────────

function createDrawer(): { drawer: AttackDetailDrawer; container: HTMLElement } {
  const container = document.createElement("div")
  const drawer = new AttackDetailDrawer(container)
  return { drawer, container }
}

function getContentEl(container: HTMLElement): HTMLElement | null {
  return container.querySelector(".ag-drawer-content")
}

// ──────────────────────────────────────────────
//  Tests
// ──────────────────────────────────────────────

describe("AttackDetailDrawer", () => {
  let drawer: AttackDetailDrawer
  let container: HTMLElement

  beforeEach(() => {
    const result = createDrawer()
    drawer = result.drawer
    container = result.container
  })

  // ── Constructor ──

  test("constructor creates overlay and panel elements", () => {
    expect(container.querySelector(".ag-drawer-overlay")).toBeTruthy()
    expect(container.querySelector(".ag-drawer-panel")).toBeTruthy()
    expect(container.querySelector(".ag-drawer-content")).toBeTruthy()
  })

  test("constructor sets role and aria attributes on panel", () => {
    const panel = container.querySelector(".ag-drawer-panel")!
    expect(panel.getAttribute("role")).toBe("dialog")
    expect(panel.getAttribute("aria-modal")).toBe("true")
  })

  // ── open() / close() ──

  test("open() adds open class and locks body scroll", () => {
    drawer.open()
    expect(container.querySelector(".ag-drawer-overlay")!.classList.contains("open")).toBe(true)
    expect(container.querySelector(".ag-drawer-panel")!.classList.contains("open")).toBe(true)
    expect(document.body.style.overflow).toBe("hidden")
  })

  test("close() removes open class and restores body scroll", () => {
    drawer.open()
    drawer.close()
    expect(container.querySelector(".ag-drawer-overlay")!.classList.contains("open")).toBe(false)
    expect(container.querySelector(".ag-drawer-panel")!.classList.contains("open")).toBe(false)
    expect(document.body.style.overflow).toBe("")
  })

  test("isOpen reflects drawer state", () => {
    expect(drawer.isOpen).toBe(false)
    drawer.open()
    expect(drawer.isOpen).toBe(true)
    drawer.close()
    expect(drawer.isOpen).toBe(false)
  })

  test("overlay click closes the drawer", () => {
    drawer.open()
    expect(drawer.isOpen).toBe(true)
    container.querySelector(".ag-drawer-overlay")!.dispatchEvent(new MouseEvent("click", { bubbles: true }))
    expect(drawer.isOpen).toBe(false)
  })

  // ── openFinding() ──

  test("openFinding renders finding details", () => {
    drawer.openFinding(SAMPLE_FINDING)
    expect(drawer.isOpen).toBe(true)

    const content = getContentEl(container)
    expect(content?.querySelector(".ag-severity-badge")?.textContent).toBe("HIGH")
    expect(content?.querySelector("h2")?.textContent).toBe("XSS")
    expect(content?.querySelector(".ag-endpoint")?.textContent).toBe("/search")
    expect(content?.querySelector(".ag-cvss")?.textContent).toBe("7.5")
    expect(content?.querySelector(".ag-conf-pct")?.textContent).toBe("92%")

    // Prerequisites and downstream impacts are in separate .ag-list elements
    const listSections = content?.querySelectorAll(".ag-list")
    expect(listSections?.length).toBe(2)
    expect(listSections?.[0]?.textContent).toContain("User must be logged in")
    expect(listSections?.[1]?.textContent).toContain("Session theft")
  })

  test("openFinding renders chain section when chainData provided", () => {
    // Use a finding ID that exists in the chain nodes
    const chainFinding: GraphNodeData = { ...SAMPLE_FINDING, id: "vuln_001" }
    drawer.openFinding(chainFinding, SAMPLE_CHAIN)
    const content = getContentEl(container)
    expect(content?.querySelector(".ag-chain-section")).toBeTruthy()
    expect(content?.querySelector(".ag-chain-badge")?.textContent).toContain("XSS → CSRF → ATO")
    expect(content?.querySelector(".ag-chain-position")?.textContent).toContain("Position 1 of 2")
  })

  test("openFinding omits chain section when no chainData", () => {
    drawer.openFinding(SAMPLE_FINDING)
    const content = getContentEl(container)
    expect(content?.querySelector(".ag-chain-section")).toBeNull()
  })

  // ── openChain() — basic ──

  test("openChain renders chain header with severity badge and risk score", () => {
    drawer.openChain(SAMPLE_CHAIN)
    const content = getContentEl(container)
    expect(content?.querySelector("h2")?.textContent).toBe("XSS → CSRF → ATO")
    // Max severity among nodes is HIGH
    const badges = content?.querySelectorAll(".ag-severity-badge")
    expect(badges?.length).toBeGreaterThanOrEqual(1)
    expect(content?.querySelector(".ag-risk-score")?.textContent).toContain("Risk 8.5")
  })

  test("openChain renders attack path steps", () => {
    drawer.openChain(SAMPLE_CHAIN)
    const content = getContentEl(container)
    const steps = content?.querySelectorAll(".ag-chain-step")
    expect(steps?.length).toBe(2)
    expect(steps?.[0]?.querySelector(".ag-step-type")?.textContent).toBe("XSS")
    expect(steps?.[1]?.querySelector(".ag-step-type")?.textContent).toBe("CSRF")
  })

  test("openChain renders risk score bar", () => {
    drawer.openChain(SAMPLE_CHAIN)
    const content = getContentEl(container)
    expect(content?.querySelector(".ag-risk-bar")).toBeTruthy()
    expect(content?.querySelector(".ag-risk-fill")).toBeTruthy()
    expect(content?.querySelector(".ag-risk-value")?.textContent).toContain("8.5")
  })

  test("openChain renders relationship edges when present", () => {
    drawer.openChain(SAMPLE_CHAIN)
    const content = getContentEl(container)
    const edgeItems = content?.querySelectorAll(".ag-list li")
    expect(edgeItems?.length).toBe(1)
    expect(edgeItems?.[0]?.textContent).toContain("enables")
    expect(edgeItems?.[0]?.textContent).toContain("×1.40")
  })

  // ── renderExploitScriptSection() via openChain() ──

  test("openChain renders exploit script section when chain has chain_exploit_script", () => {
    drawer.openChain(CHAIN_WITH_VERIFICATION)
    const content = getContentEl(container)
    const headings = content?.querySelectorAll("h3")
    const exploitHeading = Array.from(headings ?? []).find(h => h.textContent === "Exploit Script")
    expect(exploitHeading).toBeTruthy()
  })

  test("exploit script section shows script length in summary", () => {
    drawer.openChain(CHAIN_WITH_VERIFICATION)
    const content = getContentEl(container)
    const summary = content?.querySelector(".ag-script-summary")
    expect(summary?.textContent).toContain("chars")
    expect(summary?.textContent).toContain("Show exploit script")
  })

  test("exploit script section contains the script text in a code block", () => {
    drawer.openChain(CHAIN_WITH_VERIFICATION)
    const content = getContentEl(container)
    const code = content?.querySelector(".ag-script-code")
    expect(code?.textContent).toContain("#!/bin/bash")
    expect(code?.textContent).toContain("XSS → CSRF → ATO chain")
    expect(code?.textContent).toContain("curl -X POST")
  })

  test("exploit script section renders steps as ordered list", () => {
    drawer.openChain(CHAIN_WITH_VERIFICATION)
    const content = getContentEl(container)
    const steps = content?.querySelectorAll(".ag-step-list li")
    expect(steps?.length).toBe(3)
    expect(steps?.[0]?.textContent).toContain("Inject XSS payload")
    expect(steps?.[1]?.textContent).toContain("Steal CSRF token")
    expect(steps?.[2]?.textContent).toContain("account takeover")
  })

  test("exploit script section renders impact summary", () => {
    drawer.openChain(CHAIN_WITH_VERIFICATION)
    const content = getContentEl(container)
    expect(content?.querySelector(".ag-impact-text")?.textContent).toContain("Full account takeover")
  })

  test("openChain omits exploit script section when no chain_exploit_script", () => {
    drawer.openChain(SAMPLE_CHAIN)
    const content = getContentEl(container)
    expect(content?.textContent).not.toContain("Exploit Script")
  })

  test("openChain handles string-format exploit script (not object)", () => {
    drawer.openChain(CHAIN_WITH_STRING_SCRIPT)
    const content = getContentEl(container)
    expect(content?.querySelector(".ag-script-code")?.textContent).toContain("simple script")
    // No steps for string-only scripts
    expect(content?.querySelector(".ag-step-list")).toBeNull()
    expect(content?.querySelector(".ag-impact-text")).toBeNull()
  })

  // ── renderVerificationSection() via openChain() ──

  test("openChain renders verification section when chain has verification data", () => {
    drawer.openChain(CHAIN_WITH_VERIFICATION)
    const content = getContentEl(container)
    const headings = content?.querySelectorAll("h3")
    const verificationHeading = Array.from(headings ?? []).find(h => h.textContent === "Verification Status")
    expect(verificationHeading).toBeTruthy()
  })

  test("verification section shows verified badge with checkmark for successful verification", () => {
    drawer.openChain(CHAIN_WITH_VERIFICATION)
    const content = getContentEl(container)
    const status = content?.querySelector(".ag-verification-status")
    expect(status?.classList.contains("verified")).toBe(true)
    expect(status?.classList.contains("unverified")).toBe(false)
    expect(status?.querySelector(".ag-verification-label")?.textContent).toBe("Verified")
    expect(status?.querySelector(".ag-verification-icon")?.textContent).toBe("✓")
  })

  test("verification section shows unverified badge for failed verification", () => {
    drawer.openChain(CHAIN_FAILED_VERIFICATION)
    const content = getContentEl(container)
    const status = content?.querySelector(".ag-verification-status")
    expect(status?.classList.contains("unverified")).toBe(true)
    expect(status?.classList.contains("verified")).toBe(false)
    expect(status?.querySelector(".ag-verification-label")?.textContent).toBe("Not Verified")
    expect(status?.querySelector(".ag-verification-icon")?.textContent).toBe("○")
  })

  test("verification section shows confidence level", () => {
    drawer.openChain(CHAIN_WITH_VERIFICATION)
    const content = getContentEl(container)
    expect(content?.querySelector(".ag-verification-conf")?.textContent).toContain("high confidence")
  })

  test("verification section shows reason text", () => {
    drawer.openChain(CHAIN_WITH_VERIFICATION)
    const content = getContentEl(container)
    expect(content?.querySelector(".ag-verification-reason")?.textContent).toContain("All 3 exploit steps")
  })

  test("openChain omits verification section when no verification data", () => {
    drawer.openChain(CHAIN_WITHOUT_VERIFICATION)
    const content = getContentEl(container)
    expect(content?.textContent).not.toContain("Verification Status")
  })

  // ── Escape key closes drawer ──

  test("Escape key closes the drawer when open", () => {
    drawer.openChain(SAMPLE_CHAIN)
    expect(drawer.isOpen).toBe(true)

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))
    expect(drawer.isOpen).toBe(false)
  })

  test("Escape key does nothing when drawer is closed", () => {
    // Dispatch Escape while closed — should not error
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))
    expect(drawer.isOpen).toBe(false)
  })

  // ── XSS prevention ──

  test("escapes HTML in user-controlled fields to prevent XSS", () => {
    const maliciousFinding: GraphNodeData = {
      ...SAMPLE_FINDING,
      data: {
        ...SAMPLE_FINDING.data,
        type: "<script>alert('XSS')</script>",
        endpoint: "javascript:alert(1)",
      },
    }

    drawer.openFinding(maliciousFinding)
    const content = getContentEl(container)

    // Script tag should be escaped, not executed
    expect(content?.innerHTML).not.toContain("<script>alert")
    expect(content?.innerHTML).toContain("&lt;script&gt;alert")
  })

  // ── Chain with all new features combined ──

  test("openChain renders exploit + verification sections together when both present", () => {
    drawer.openChain(CHAIN_WITH_VERIFICATION)
    const content = getContentEl(container)

    // Both sections present
    expect(content?.querySelector(".ag-script-details")).toBeTruthy()
    expect(content?.querySelector(".ag-verification-status")).toBeTruthy()

    // Script content is correct
    expect(content?.querySelector(".ag-script-code")?.textContent).toContain("XSS → CSRF → ATO chain")

    // Verification shows checkmark
    expect(content?.querySelector(".ag-verification-icon")?.textContent).toBe("✓")
  })

  // ── Chain with failed verification ──

  test("failed verification shows reason explaining failure", () => {
    drawer.openChain(CHAIN_FAILED_VERIFICATION)
    const content = getContentEl(container)
    expect(content?.querySelector(".ag-verification-reason")?.textContent).toContain("Network connection to target failed")
    expect(content?.querySelector(".ag-verification-conf")?.textContent).toContain("low confidence")
  })
})
