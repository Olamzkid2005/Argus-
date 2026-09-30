/**
 * Scope resolution tests.
 *
 * `argus.config.yaml` ships mode: warn with an empty allowed_targets list, so an
 * authorized run needs a way to declare its scope without editing committed
 * config — and `doctor` plus the autonomous-mode guard must read exactly the
 * values the enforcer uses. These tests pin ARGUS_SCOPE_MODE /
 * ARGUS_ALLOWED_TARGETS and their precedence over the file.
 */

import { afterEach, beforeEach, describe, expect, test } from "bun:test"
import { PROJECT_ROOT } from "../../../../src/argus/shared/path"

const ENV_MODE = "ARGUS_SCOPE_MODE"
const ENV_TARGETS = "ARGUS_ALLOWED_TARGETS"

let savedCwd = process.cwd()
let savedEnv: Record<string, string | undefined> = {}

beforeEach(() => {
  savedCwd = process.cwd()
  savedEnv = { [ENV_MODE]: process.env[ENV_MODE], [ENV_TARGETS]: process.env[ENV_TARGETS] }
  delete process.env[ENV_MODE]
  delete process.env[ENV_TARGETS]
  // Default to a directory with no argus.config.yaml so the file path is not a
  // variable in most of these tests.
  process.chdir(import.meta.dir)
})

afterEach(() => {
  process.chdir(savedCwd)
  for (const [key, value] of Object.entries(savedEnv)) {
    if (value === undefined) delete process.env[key]
    else process.env[key] = value
  }
})

async function loadScope() {
  const { TargetValidator } = await import("../../../../src/argus/shared/target-validator")
  // No constructor config => load() reads the file (if any) then env overrides.
  return new TargetValidator().load().scope!
}

describe("scope configuration resolution", () => {
  test("defaults to warn with no targets when nothing is configured", async () => {
    const scope = await loadScope()
    expect(scope.mode).toBe("warn")
    expect(scope.allowed_targets).toEqual([])
  })

  test("reads mode and targets from argus.config.yaml", async () => {
    process.chdir(PROJECT_ROOT)
    const scope = await loadScope()
    // The committed config is intentionally conservative.
    expect(scope.mode).toBe("warn")
  })

  test("ARGUS_SCOPE_MODE overrides the file", async () => {
    process.chdir(PROJECT_ROOT)
    process.env[ENV_MODE] = "allowlist"
    const scope = await loadScope()
    expect(scope.mode).toBe("allowlist")
  })

  test("ARGUS_ALLOWED_TARGETS is parsed, trimmed and overrides the file", async () => {
    process.chdir(PROJECT_ROOT)
    process.env[ENV_TARGETS] = " 127.0.0.1 , example.com ,, "
    const scope = await loadScope()
    expect(scope.allowed_targets).toEqual(["127.0.0.1", "example.com"])
  })

  test("env overrides apply even with no config file", async () => {
    process.env[ENV_MODE] = "allowlist"
    process.env[ENV_TARGETS] = "127.0.0.1"
    const scope = await loadScope()
    expect(scope.mode).toBe("allowlist")
    expect(scope.allowed_targets).toEqual(["127.0.0.1"])
  })

  test("a blank ARGUS_ALLOWED_TARGETS does not clear the file's targets", async () => {
    process.chdir(PROJECT_ROOT)
    process.env[ENV_TARGETS] = "   "
    const scope = await loadScope()
    // Committed config has no targets; the point is that the blank value is
    // ignored rather than producing [""].
    expect(scope.allowed_targets).toEqual([])
  })

  test("env-scoped allowlist actually rejects out-of-scope targets", async () => {
    process.env[ENV_MODE] = "allowlist"
    process.env[ENV_TARGETS] = "127.0.0.1"
    const { TargetValidator } = await import("../../../../src/argus/shared/target-validator")
    const validator = new TargetValidator()

    const allowed = await validator.validateTarget("http://127.0.0.1:8899")
    expect(allowed.valid).toBe(true)

    const denied = await validator.validateTarget("http://example.org")
    expect(denied.valid).toBe(false)
    expect(denied.reason).toBe("not_in_allowed_targets")
  })
})
