/**
 * Integration tests for the `/assess --no-cache` flag flow.
 *
 * These tests verify that `stripFlags` and `detectCacheMode` work correctly
 * *together*, as they are called by the TUI prompt handler in prompt/index.tsx.
 *
 * The TUI handler for `/assess`, `/scan`, and `/recon` commands:
 * 1. Reads the raw `arg` string (everything after the command word)
 * 2. Calls `stripFlags(arg)` to get the clean target URL
 * 3. Calls `detectCacheMode(arg)` to get the cache mode
 * 4. Passes both to `runner.run({ target, cacheMode, ... })`
 *
 * These tests simulate that exact flow to catch regressions where the
 * two functions might disagree (e.g., stripFlags removes a flag that
 * detectCacheMode was supposed to detect).
 */
import { describe, expect, test } from "bun:test"
import { stripFlags, detectCacheMode, hasVerboseFlag } from "../../../src/cli/cmd/tui/util/flag-strip"

/**
 * Simulates what the TUI prompt handler does when it receives `/assess <args>`.
 * Returns the parsed engagement options that would be passed to WorkflowRunner.run().
 */
function parseTuiAssessInput(rawArgs: string): {
  target: string | undefined
  cacheMode: "no_cache" | "refresh" | undefined
  verbose: boolean
} {
  const stripped = stripFlags(rawArgs)
  if (!stripped) return { target: undefined, cacheMode: undefined, verbose: false }
  return {
    target: stripped,
    cacheMode: detectCacheMode(rawArgs),
    verbose: hasVerboseFlag(rawArgs),
  }
}

describe("TUI /assess flag flow integration", () => {
  // ── Happy paths ──────────────────────────────────────────────

  test("/assess example.com --no-cache → target=example.com, cacheMode=no_cache", () => {
    const result = parseTuiAssessInput("example.com --no-cache")
    expect(result.target).toBe("example.com")
    expect(result.cacheMode).toBe("no_cache")
  })

  test("/assess https://example.com --refresh-cache → target=URL, cacheMode=refresh", () => {
    const result = parseTuiAssessInput("https://example.com --refresh-cache")
    expect(result.target).toBe("https://example.com")
    expect(result.cacheMode).toBe("refresh")
  })

  test("/assess https://example.com (no flags) → target=URL, cacheMode=undefined", () => {
    const result = parseTuiAssessInput("https://example.com")
    expect(result.target).toBe("https://example.com")
    expect(result.cacheMode).toBeUndefined()
  })

  // ── Flag ordering ────────────────────────────────────────────

  test("--no-cache before target still works", () => {
    const result = parseTuiAssessInput("--no-cache https://example.com")
    expect(result.target).toBe("https://example.com")
    expect(result.cacheMode).toBe("no_cache")
  })

  test("--refresh-cache before target still works", () => {
    const result = parseTuiAssessInput("--refresh-cache https://example.com")
    expect(result.target).toBe("https://example.com")
    expect(result.cacheMode).toBe("refresh")
  })

  test("flags on both sides of target still work", () => {
    const result = parseTuiAssessInput("--no-cache https://example.com --refresh-cache")
    expect(result.target).toBe("https://example.com")
    // --no-cache takes precedence
    expect(result.cacheMode).toBe("no_cache")
  })

  // ── Precedence rules ─────────────────────────────────────────

  test("--no-cache wins over --refresh-cache when both present", () => {
    const result = parseTuiAssessInput("https://example.com --no-cache --refresh-cache")
    expect(result.target).toBe("https://example.com")
    expect(result.cacheMode).toBe("no_cache")
  })

  test("--no-cache wins over --refresh-cache regardless of order", () => {
    const r1 = parseTuiAssessInput("https://example.com --refresh-cache --no-cache")
    expect(r1.cacheMode).toBe("no_cache")
    const r2 = parseTuiAssessInput("--no-cache --refresh-cache https://example.com")
    expect(r2.cacheMode).toBe("no_cache")
  })

  // ── Edge cases ────────────────────────────────────────────────

  test("unrelated flags do not affect cacheMode but verbose is detected", () => {
    const result = parseTuiAssessInput("https://example.com --verbose --debug")
    expect(result.target).toBe("https://example.com")
    expect(result.cacheMode).toBeUndefined()
    expect(result.verbose).toBe(true)
  })

  test("partial flag match (-refresh) does not trigger cache mode", () => {
    const result = parseTuiAssessInput("https://example.com --refresh")
    expect(result.target).toBe("https://example.com")
    expect(result.cacheMode).toBeUndefined()
  })

  test("flags-only input returns undefined target and undefined cacheMode (TUI short-circuits)", () => {
    // The TUI handler short-circuits when strippedTarget is falsy → shows error toast.
    // cacheMode is never used because the handler returns early. undefined is correct.
    const result = parseTuiAssessInput("--no-cache --refresh-cache")
    expect(result.target).toBeUndefined()
    expect(result.cacheMode).toBeUndefined()
    expect(result.verbose).toBe(false)
  })

  test("empty input returns undefined target and cacheMode", () => {
    const result = parseTuiAssessInput("")
    expect(result.target).toBeUndefined()
    expect(result.cacheMode).toBeUndefined()
    expect(result.verbose).toBe(false)
  })

  // ── Realistic TUI scenarios ──────────────────────────────────

  test("/assess 192.168.1.1:8080 --no-cache (IP:port target)", () => {
    const result = parseTuiAssessInput("192.168.1.1:8080 --no-cache")
    expect(result.target).toBe("192.168.1.1:8080")
    expect(result.cacheMode).toBe("no_cache")
    expect(result.verbose).toBe(false)
  })

  test("/assess https://juice-shop.example.com --no-cache (subdomain)", () => {
    const result = parseTuiAssessInput("https://juice-shop.example.com --no-cache")
    expect(result.target).toBe("https://juice-shop.example.com")
    expect(result.cacheMode).toBe("no_cache")
  })

  test("/assess target --no-cache with extra whitespace", () => {
    const result = parseTuiAssessInput("  https://example.com   --no-cache   ")
    expect(result.target).toBe("https://example.com")
    expect(result.cacheMode).toBe("no_cache")
    expect(result.verbose).toBe(false)
  })

  test("/scan target --refresh-cache uses same flow as /assess", () => {
    const result = parseTuiAssessInput("https://example.com --refresh-cache")
    expect(result.target).toBe("https://example.com")
    expect(result.cacheMode).toBe("refresh")
    expect(result.verbose).toBe(false)
  })

  test("/recon target --no-cache uses same flow as /assess", () => {
    const result = parseTuiAssessInput("https://example.com --no-cache")
    expect(result.target).toBe("https://example.com")
    expect(result.cacheMode).toBe("no_cache")
    expect(result.verbose).toBe(false)
  })

  /**
   * Regression: The TUI handler previously passed the raw `arg` (with flags)
   * to `runner.run({ target: arg, ... })`, which meant `--no-cache` would
   * become part of the engagement's target URL in SQLite.
   *
   * This test verifies that `stripFlags()` removes all CLI flags so the
   * engagement target is always a clean URL/hostname.
   */
  test("REGRESSION: flags do not leak into the cleaned target", () => {
    const leakyInputs = [
      "example.com --no-cache",
      "example.com --refresh-cache",
      "example.com --no-cache --refresh-cache",
      "--no-cache example.com",
      "--refresh-cache example.com",
      "--no-cache --refresh-cache example.com",
      "example.com --no-cache --verbose",
    ]
    for (const input of leakyInputs) {
      const result = parseTuiAssessInput(input)
      expect(result.target).toBe("example.com")
      expect(result.target).not.toContain("--")
    }
  })

  /**
   * Regression: The TUI handler must use the *same* raw `arg` for both
   * stripFlags and detectCacheMode, not a pre-stripped version.
   * If detectCacheMode receives the already-stripped target, it would
   * never find the cache flags and would always return undefined.
   */
  test("detectCacheMode receives the raw arg (with flags), not the stripped target", () => {
    // This simulates what happens if someone accidentally passes
    // the stripped target to detectCacheMode instead of the raw arg.
    const rawArg = "example.com --no-cache"
    const stripped = stripFlags(rawArg) // "example.com"

    // Correct: detectCacheMode gets the raw arg
    const correct = detectCacheMode(rawArg)
    expect(correct).toBe("no_cache")

    // Wrong: if detectCacheMode got the stripped target
    const wrong = detectCacheMode(stripped)
    expect(wrong).toBeUndefined()

    // Assert they differ, proving the raw arg must be used
    expect(correct).not.toBe(wrong)
  })

  // ── Full round-trip tests (simulating the TUI handler) ──────

  test("full round-trip: /assess https://example.com --no-cache", () => {
    // This is exactly what the TUI handler does
    const rawArg = "https://example.com --no-cache"

    // Step 1: Strip flags for engagement creation & navigation
    const cleanedTarget = stripFlags(rawArg)
    expect(cleanedTarget).toBe("https://example.com")

    // Step 2: Detect cache mode for executor
    const cacheMode = detectCacheMode(rawArg)
    expect(cacheMode).toBe("no_cache")

    // Step 3: Build the runner options (as the TUI handler does)
    const runnerOptions = {
      target: cleanedTarget,
      cacheMode,
      useLLM: true,
    }
    expect(runnerOptions.target).toBe("https://example.com")
    expect(runnerOptions.cacheMode).toBe("no_cache")
    expect(runnerOptions.useLLM).toBe(true)
  })

  test("full round-trip: /recon 192.168.1.1 --refresh-cache", () => {
    const rawArg = "192.168.1.1 --refresh-cache"

    const cleanedTarget = stripFlags(rawArg)
    expect(cleanedTarget).toBe("192.168.1.1")

    const cacheMode = detectCacheMode(rawArg)
    expect(cacheMode).toBe("refresh")

    const runnerOptions = {
      target: cleanedTarget,
      cacheMode,
      useLLM: false, // recon doesn't use LLM
    }
    expect(runnerOptions.target).toBe("192.168.1.1")
    expect(runnerOptions.cacheMode).toBe("refresh")
  })

  test("full round-trip: /scan https://example.com (no flags)", () => {
    const rawArg = "https://example.com"

    const cleanedTarget = stripFlags(rawArg)
    expect(cleanedTarget).toBe("https://example.com")

    const cacheMode = detectCacheMode(rawArg)
    expect(cacheMode).toBeUndefined()

    const runnerOptions = {
      target: cleanedTarget,
      cacheMode,
      useLLM: true,
    }
    expect(runnerOptions.target).toBe("https://example.com")
    expect(runnerOptions.cacheMode).toBeUndefined()
  })

  test("full round-trip: /assess http://testphp.vulnweb.com --no-cache --verbose", () => {
    // Realistic: extra flags that should be stripped but not affect cache detection
    const rawArg = "http://testphp.vulnweb.com --no-cache --verbose"

    const cleanedTarget = stripFlags(rawArg)
    expect(cleanedTarget).toBe("http://testphp.vulnweb.com")

    const cacheMode = detectCacheMode(rawArg)
    expect(cacheMode).toBe("no_cache")

    const verbose = hasVerboseFlag(rawArg)
    expect(verbose).toBe(true)

    const runnerOptions = {
      target: cleanedTarget,
      cacheMode,
      verbose,
    }
    expect(runnerOptions.target).toBe("http://testphp.vulnweb.com")
    expect(runnerOptions.cacheMode).toBe("no_cache")
    expect(runnerOptions.verbose).toBe(true)
  })

  // ── --verbose-specific tests ─────────────────────────────────

  test("/assess example.com --verbose → target=stripped, cacheMode=undefined, verbose=true", () => {
    const result = parseTuiAssessInput("example.com --verbose")
    expect(result.target).toBe("example.com")
    expect(result.cacheMode).toBeUndefined()
    expect(result.verbose).toBe(true)
  })

  test("/assess https://example.com --verbose --no-cache → verbose=true with cacheMode=no_cache", () => {
    const result = parseTuiAssessInput("https://example.com --verbose --no-cache")
    expect(result.target).toBe("https://example.com")
    expect(result.cacheMode).toBe("no_cache")
    expect(result.verbose).toBe(true)
  })

  test("--verbose before target still works", () => {
    const result = parseTuiAssessInput("--verbose https://example.com --no-cache")
    expect(result.target).toBe("https://example.com")
    expect(result.cacheMode).toBe("no_cache")
    expect(result.verbose).toBe(true)
  })

  test("--verbose is stripped from target and does not leak", () => {
    const result = parseTuiAssessInput("https://example.com --verbose")
    expect(result.target).toBe("https://example.com")
    expect(result.target).not.toContain("--verbose")
    expect(result.verbose).toBe(true)
  })

  test("full round-trip: /assess target --verbose with all three flags", () => {
    const rawArg = "https://example.com --no-cache --refresh-cache --verbose"

    const cleanedTarget = stripFlags(rawArg)
    expect(cleanedTarget).toBe("https://example.com")

    const cacheMode = detectCacheMode(rawArg)
    expect(cacheMode).toBe("no_cache") // --no-cache wins over --refresh-cache

    const verbose = hasVerboseFlag(rawArg)
    expect(verbose).toBe(true)

    const runnerOptions = {
      target: cleanedTarget,
      cacheMode,
      verbose,
      useLLM: true,
    }
    expect(runnerOptions).toEqual({
      target: "https://example.com",
      cacheMode: "no_cache",
      verbose: true,
      useLLM: true,
    })
  })

  test("/scan example.com --verbose (recon command uses verbose too)", () => {
    const result = parseTuiAssessInput("example.com --verbose")
    expect(result.target).toBe("example.com")
    expect(result.cacheMode).toBeUndefined()
    expect(result.verbose).toBe(true)
  })

  test("/recon 10.0.0.1 --verbose --refresh-cache", () => {
    const result = parseTuiAssessInput("10.0.0.1 --verbose --refresh-cache")
    expect(result.target).toBe("10.0.0.1")
    expect(result.cacheMode).toBe("refresh")
    expect(result.verbose).toBe(true)
  })
})
