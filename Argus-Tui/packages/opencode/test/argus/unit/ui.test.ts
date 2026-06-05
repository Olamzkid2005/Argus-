import { describe, it, expect, mock, beforeEach, afterEach } from "bun:test"

const { Style, println, print, empty, error, logo, markdown, dashboard } = await import("../../../src/argus/ui")

describe("Style constants", () => {
  it("contain ANSI escape codes", () => {
    expect(Style.TEXT_HIGHLIGHT).toBe("\x1b[96m")
    expect(Style.TEXT_HIGHLIGHT_BOLD).toBe("\x1b[96m\x1b[1m")
    expect(Style.TEXT_DIM).toBe("\x1b[90m")
    expect(Style.TEXT_DIM_BOLD).toBe("\x1b[90m\x1b[1m")
    expect(Style.TEXT_NORMAL).toBe("\x1b[0m")
    expect(Style.TEXT_NORMAL_BOLD).toBe("\x1b[1m")
    expect(Style.TEXT_WARNING).toBe("\x1b[93m")
    expect(Style.TEXT_WARNING_BOLD).toBe("\x1b[93m\x1b[1m")
    expect(Style.TEXT_DANGER).toBe("\x1b[91m")
    expect(Style.TEXT_DANGER_BOLD).toBe("\x1b[91m\x1b[1m")
    expect(Style.TEXT_SUCCESS).toBe("\x1b[92m")
    expect(Style.TEXT_SUCCESS_BOLD).toBe("\x1b[92m\x1b[1m")
    expect(Style.TEXT_INFO).toBe("\x1b[94m")
    expect(Style.TEXT_INFO_BOLD).toBe("\x1b[94m\x1b[1m")
  })
})

describe("print/println/empty/error", () => {
  let writes: string[]
  let origWrite: typeof process.stderr.write

  beforeEach(() => {
    writes = []
    origWrite = process.stderr.write
    process.stderr.write = ((s: string) => { writes.push(s); return true }) as any
  })

  afterEach(() => {
    process.stderr.write = origWrite
  })

  it("println() writes to stderr with newline", () => {
    println("hello", "world")
    expect(writes).toEqual(["hello world", "\n"])
  })

  it("print() writes to stderr without newline", () => {
    print("hello")
    expect(writes).toEqual(["hello"])
  })

  it("empty() writes blank line on first call, skips on subsequent", () => {
    empty()
    empty()
    expect(writes).toHaveLength(2)
    expect(writes[0]).toBe("\x1b[0m")
    expect(writes[1]).toBe("\n")
  })

  it("error() strips \"Error: \" prefix and writes with danger style", () => {
    error("Error: something broke")
    expect(writes).toHaveLength(2)
    expect(writes[0]).toBe("\x1b[91m\x1b[1mError: \x1b[0msomething broke")
    expect(writes[1]).toBe("\n")
  })

  it("error() does not strip non-prefixed messages", () => {
    error("something broke")
    expect(writes[0]).toContain("something broke")
  })
})

describe("logo", () => {
  const origStdoutIsTTY = process.stdout.isTTY
  const origStderrIsTTY = process.stderr.isTTY

  afterEach(() => {
    process.stdout.isTTY = origStdoutIsTTY
    process.stderr.isTTY = origStderrIsTTY
  })

  it("without TTY returns plain text with wordmark", () => {
    process.stdout.isTTY = false
    process.stderr.isTTY = false
    const result = logo()
    expect(result).toContain("ARGUS")
    expect(result).toContain("███")
    expect(result).not.toContain("\x1b")
  })

  it("with TTY returns ANSI-styled output", () => {
    process.stdout.isTTY = true
    process.stderr.isTTY = true
    const result = logo()
    expect(result).toContain("ARGUS")
    expect(result).toContain("\x1b")
  })
})

describe("markdown", () => {
  it("passes through unchanged", () => {
    expect(markdown("hello **world**")).toBe("hello **world**")
  })
})

// ── Dashboard rendering ─────────────────────────────────────────────

describe("dashboard", () => {
  const origStdoutTTY = process.stdout.isTTY
  const origStderrTTY = process.stderr.isTTY

  beforeEach(() => {
    process.stdout.isTTY = true
    process.stderr.isTTY = true
  })

  afterEach(() => {
    process.stdout.isTTY = origStdoutTTY
    process.stderr.isTTY = origStderrTTY
  })

  it("renders the logo and platform name", () => {
    const result = dashboard()
    expect(result).toContain("ARGUS v5")
    expect(result).toContain("Autonomous Security Assessment Platform")
  })

  it("includes quick actions section", () => {
    const result = dashboard()
    expect(result).toContain("$ argus assess")
    expect(result).toContain("$ argus recon")
    expect(result).toContain("$ argus doctor")
  })

  it("shows empty state when no stats provided", () => {
    const result = dashboard()
    expect(result).toContain("No assessments yet")
  })

  it("shows stats when provided", () => {
    const result = dashboard({
      totalTargets: 5,
      openEngagements: 2,
      confirmedFindings: 12,
      recentEngagements: [
        { id: "ENG-001", target: "example.com", status: "COMPLETED", findingCount: 8, updatedAt: Date.now() },
        { id: "ENG-002", target: "test.com", status: "RUNNING", findingCount: 3, updatedAt: Date.now() },
      ],
    })
    expect(result).toContain("5")
    expect(result).toContain("targets")
    expect(result).toContain("2")
    expect(result).toContain("active")
    expect(result).toContain("12")
    expect(result).toContain("findings")
  })

  it("shows recent engagements when provided", () => {
    const result = dashboard({
      totalTargets: 1,
      openEngagements: 0,
      confirmedFindings: 0,
      recentEngagements: [
        { id: "ENG-001", target: "example.com", status: "COMPLETED", findingCount: 8, updatedAt: Date.now() },
      ],
    })
    expect(result).toContain("ENG-001")
    expect(result).toContain("example.com")
    expect(result).toContain("completed")
  })

  it("shows ANSI style codes in output", () => {
    const result = dashboard()
    expect(result).toContain("\x1b[") // ANSI escape
  })

  it("limits recent engagements to 5", () => {
    const many = Array.from({ length: 10 }, (_, i) => ({
      id: `ENG-${String(i).padStart(3, "0")}`,
      target: `target-${i}.com`,
      status: "COMPLETED",
      findingCount: i,
      updatedAt: Date.now(),
    }))
    const result = dashboard({ totalTargets: 10, openEngagements: 0, confirmedFindings: 0, recentEngagements: many })
    // Should contain first 5
    expect(result).toContain("ENG-000")
    expect(result).toContain("ENG-004")
    // Should NOT contain the 6th
    expect(result).not.toContain("ENG-005")
  })
})
