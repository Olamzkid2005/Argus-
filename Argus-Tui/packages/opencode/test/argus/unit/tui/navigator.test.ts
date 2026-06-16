import { describe, it, expect, mock } from "bun:test"
import {
  setNavigateHandler,
  clearNavigateHandler,
  navigateTo,
} from "../../../../src/argus/tui/navigator"
import type { ArgusRoute } from "../../../../src/argus/tui/navigator"

describe("navigator", () => {
  it("setNavigateHandler() stores the handler", () => {
    const handler = mock()
    setNavigateHandler(handler)
    navigateTo({ type: "scan", target: "https://test.com", engagementId: "eng-123" })
    expect(handler).toHaveBeenCalledWith({
      type: "scan",
      target: "https://test.com",
      engagementId: "eng-123",
    })
    clearNavigateHandler()
  })

  it("navigateTo() calls the handler with findings route", () => {
    const handler = mock()
    setNavigateHandler(handler)
    navigateTo({ type: "findings", engagementId: "eng-456" })
    expect(handler).toHaveBeenCalledWith({
      type: "findings",
      engagementId: "eng-456",
    })
    clearNavigateHandler()
  })

  it("navigateTo() does nothing when no handler is set", () => {
    clearNavigateHandler()
    expect(() => {
      navigateTo({ type: "scan", target: "https://test.com", engagementId: "eng-1" })
    }).not.toThrow()
  })

  it("clearNavigateHandler() removes the handler", () => {
    const handler = mock()
    setNavigateHandler(handler)
    clearNavigateHandler()
    navigateTo({ type: "scan", target: "https://test.com", engagementId: "eng-1" })
    expect(handler).not.toHaveBeenCalled()
  })
})

// ── New route types (dashboard, engagements, workspace) ──────────────

describe("navigator — new route types", () => {
  it("navigates to dashboard", () => {
    const handler = mock()
    setNavigateHandler(handler)
    navigateTo({ type: "dashboard" })
    expect(handler).toHaveBeenCalledWith({ type: "dashboard" })
    clearNavigateHandler()
  })

  it("navigates to engagements list", () => {
    const handler = mock()
    setNavigateHandler(handler)
    navigateTo({ type: "engagements" })
    expect(handler).toHaveBeenCalledWith({ type: "engagements" })
    clearNavigateHandler()
  })

  it("navigates to workspace", () => {
    const handler = mock()
    setNavigateHandler(handler)
    navigateTo({ type: "workspace" })
    expect(handler).toHaveBeenCalledWith({ type: "workspace" })
    clearNavigateHandler()
  })

  it("navigates to engagement detail", () => {
    const handler = mock()
    setNavigateHandler(handler)
    navigateTo({ type: "engagement", engagementId: "ENG-001" })
    expect(handler).toHaveBeenCalledWith({ type: "engagement", engagementId: "ENG-001" })
    clearNavigateHandler()
  })
})

// ── ArgusRoute type exhaustiveness check ────────────────────────────

describe("ArgusRoute type", () => {
  it("accepts all valid route shapes at compile time", () => {
    const routes: ArgusRoute[] = [
      { type: "dashboard" },
      { type: "scan", target: "x", engagementId: "y" },
      { type: "findings" },
      { type: "findings", engagementId: "z" },
      { type: "engagements" },
      { type: "engagement", engagementId: "w" },
      { type: "report", engagementId: "v" },
      { type: "workspace" },
    ]
    expect(routes).toHaveLength(8)
    expect(routes.map((r) => r.type)).toEqual([
      "dashboard", "scan", "findings", "findings",
      "engagements", "engagement", "report", "workspace",
    ])
  })
})
