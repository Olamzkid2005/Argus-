import { describe, it, expect, mock } from "bun:test"
import {
  setNavigateHandler,
  clearNavigateHandler,
  navigateTo,
} from "../../../../src/argus/tui/navigator"

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
