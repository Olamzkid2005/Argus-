import { describe, it, expect, mock, beforeEach, afterEach } from "bun:test"

const { Style, println, print, empty, error, logo, markdown } = await import("../../../src/argus/ui")

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
