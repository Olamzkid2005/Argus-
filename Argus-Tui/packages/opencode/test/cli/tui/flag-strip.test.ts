import { describe, expect, test } from "bun:test"
import { stripFlags, detectCacheMode, hasVerboseFlag } from "../../../src/cli/cmd/tui/util/flag-strip"

describe("stripFlags", () => {
  test("preserves a URL with no flags", () => {
    expect(stripFlags("https://example.com")).toBe("https://example.com")
  })

  test("strips a single flag after the URL", () => {
    expect(stripFlags("https://example.com --no-cache")).toBe("https://example.com")
  })

  test("strips multiple flags after the URL", () => {
    expect(stripFlags("https://example.com --no-cache --refresh-cache")).toBe("https://example.com")
  })

  test("strips a flag before the URL", () => {
    expect(stripFlags("--no-cache https://example.com")).toBe("https://example.com")
  })

  test("strips flags on both sides of the URL", () => {
    expect(stripFlags("--no-cache https://example.com --refresh-cache")).toBe("https://example.com")
  })

  test("returns empty string when only flags are given", () => {
    expect(stripFlags("--no-cache --refresh-cache")).toBe("")
  })

  test("returns empty string for empty input", () => {
    expect(stripFlags("")).toBe("")
  })

  test("returns empty string for whitespace-only input", () => {
    expect(stripFlags("   ")).toBe("")
  })

  test("handles extra whitespace between tokens", () => {
    expect(stripFlags("https://example.com   --no-cache    --refresh-cache")).toBe("https://example.com")
  })

  test("preserves an IP:port target with flags", () => {
    expect(stripFlags("192.168.1.1:8080 --no-cache")).toBe("192.168.1.1:8080")
  })

  test("does not treat double-hyphens in the middle of a token as a flag", () => {
    // "https://example.com/--path" — the -- is part of the path, not a token start
    expect(stripFlags("https://example.com/--path")).toBe("https://example.com/--path")
  })

  test("preserves a single token target with no spaces", () => {
    expect(stripFlags("example.com")).toBe("example.com")
  })

  test("strips flag with equals sign value", () => {
    expect(stripFlags("https://example.com --flag=value")).toBe("https://example.com")
  })

  test("handles a plain hostname with flags", () => {
    expect(stripFlags("example.com --no-cache")).toBe("example.com")
  })
})

describe("detectCacheMode", () => {
  test("returns undefined when no cache flags are present", () => {
    expect(detectCacheMode("https://example.com")).toBeUndefined()
  })

  test("detects --no-cache after the URL", () => {
    expect(detectCacheMode("https://example.com --no-cache")).toBe("no_cache")
  })

  test("detects --no-cache before the URL", () => {
    expect(detectCacheMode("--no-cache https://example.com")).toBe("no_cache")
  })

  test("detects --refresh-cache after the URL", () => {
    expect(detectCacheMode("https://example.com --refresh-cache")).toBe("refresh")
  })

  test("detects --refresh-cache before the URL", () => {
    expect(detectCacheMode("--refresh-cache https://example.com")).toBe("refresh")
  })

  test("--no-cache takes precedence over --refresh-cache when both flags are present", () => {
    expect(detectCacheMode("https://example.com --no-cache --refresh-cache")).toBe("no_cache")
    expect(detectCacheMode("https://example.com --refresh-cache --no-cache")).toBe("no_cache")
  })

  test("returns undefined for empty input", () => {
    expect(detectCacheMode("")).toBeUndefined()
  })

  test("does not confuse --no-cache with unrelated flags", () => {
    expect(detectCacheMode("https://example.com --verbose")).toBeUndefined()
  })

  test("does not confuse --refresh-cache with partial matches", () => {
    // A flag that starts similarly should NOT match
    expect(detectCacheMode("https://example.com --refresh")).toBeUndefined()
  })

  test("returns undefined when only whitespace is present", () => {
    expect(detectCacheMode("   ")).toBeUndefined()
  })

  test("detects cache mode for an IP:port target", () => {
    expect(detectCacheMode("192.168.1.1:8080 --no-cache")).toBe("no_cache")
  })
})

describe("hasVerboseFlag", () => {
  test("detects --verbose after the URL", () => {
    expect(hasVerboseFlag("https://example.com --verbose")).toBe(true)
  })

  test("detects --verbose before the URL", () => {
    expect(hasVerboseFlag("--verbose https://example.com")).toBe(true)
  })

  test("detects --verbose alongside other flags", () => {
    expect(hasVerboseFlag("https://example.com --no-cache --verbose")).toBe(true)
  })

  test("returns false when no --verbose flag is present", () => {
    expect(hasVerboseFlag("https://example.com")).toBe(false)
  })

  test("returns false when --no-cache is present but --verbose is not", () => {
    expect(hasVerboseFlag("https://example.com --no-cache")).toBe(false)
  })

  test("returns false for empty input", () => {
    expect(hasVerboseFlag("")).toBe(false)
  })

  test("does not confuse --verbose with partial matches", () => {
    expect(hasVerboseFlag("https://example.com --verb")).toBe(false)
  })

  test("detects --verbose for an IP:port target", () => {
    expect(hasVerboseFlag("192.168.1.1:8080 --verbose")).toBe(true)
  })
})
