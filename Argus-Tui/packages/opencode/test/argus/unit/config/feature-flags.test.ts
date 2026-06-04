import { describe, expect, test, beforeEach } from "bun:test"
import { FeatureFlags, Feature, resetFeatureFlags } from "../../../../src/argus/config/feature-flags"

describe("FeatureFlags", () => {
  let flags: FeatureFlags

  beforeEach(() => {
    resetFeatureFlags()
    flags = new FeatureFlags()
  })

  test("all features default to false (opt-in)", () => {
    expect(flags.isEnabled(Feature.BROWSER_VERIFICATION)).toBe(false)
    expect(flags.isEnabled(Feature.WORKFLOW_REGISTRY)).toBe(false)
    expect(flags.isEnabled(Feature.ENGAGEMENT_STORE)).toBe(false)
    expect(flags.isEnabled(Feature.APPROVAL_GATES)).toBe(false)
  })

  test("DETERMINISTIC_FALLBACK defaults to true", () => {
    expect(flags.isEnabled(Feature.DETERMINISTIC_FALLBACK)).toBe(true)
  })

  test("constructor overrides enable features", () => {
    const f = new FeatureFlags({ [Feature.BROWSER_VERIFICATION]: true })
    expect(f.isEnabled(Feature.BROWSER_VERIFICATION)).toBe(true)
    expect(f.isEnabled(Feature.WORKFLOW_REGISTRY)).toBe(false)
  })

  test("applyOverrides updates features and records source", () => {
    flags.applyOverrides({ [Feature.BROWSER_VERIFICATION]: true }, "config")
    expect(flags.isEnabled(Feature.BROWSER_VERIFICATION)).toBe(true)
    const dump = flags.dump()
    expect(dump["browser_verification"].source).toBe("config")
  })

  test("allEnabled returns true only when all features are enabled", () => {
    const f = new FeatureFlags({
      [Feature.BROWSER_VERIFICATION]: true,
      [Feature.WORKFLOW_REGISTRY]: true,
    })
    expect(f.allEnabled(Feature.BROWSER_VERIFICATION, Feature.WORKFLOW_REGISTRY)).toBe(true)
    expect(f.allEnabled(Feature.BROWSER_VERIFICATION, Feature.ENGAGEMENT_STORE)).toBe(false)
  })

  test("anyEnabled returns true when any feature is enabled", () => {
    const f = new FeatureFlags({ [Feature.BROWSER_VERIFICATION]: true })
    expect(f.anyEnabled(Feature.BROWSER_VERIFICATION, Feature.ENGAGEMENT_STORE)).toBe(true)
    expect(f.anyEnabled(Feature.ENGAGEMENT_STORE, Feature.APPROVAL_GATES)).toBe(false)
  })

  test("loadFromEnv reads ARGUS_FEATURE_* environment variables", () => {
    process.env["ARGUS_FEATURE_BROWSER_VERIFICATION"] = "true"
    process.env["ARGUS_FEATURE_WORKFLOW_REGISTRY"] = "1"
    flags.loadFromEnv()
    expect(flags.isEnabled(Feature.BROWSER_VERIFICATION)).toBe(true)
    expect(flags.isEnabled(Feature.WORKFLOW_REGISTRY)).toBe(true)
    expect(flags.isEnabled(Feature.ENGAGEMENT_STORE)).toBe(false)
    delete process.env["ARGUS_FEATURE_BROWSER_VERIFICATION"]
    delete process.env["ARGUS_FEATURE_WORKFLOW_REGISTRY"]
  })

  test("loadFromConfig reads feature config object", () => {
    flags.loadFromConfig({ "browser_verification": true })
    expect(flags.isEnabled(Feature.BROWSER_VERIFICATION)).toBe(true)
  })

  test("precedence: CLI overrides env overrides config over defaults", () => {
    // config sets it true
    flags.loadFromConfig({ "browser_verification": false })
    // env overrides to true
    process.env["ARGUS_FEATURE_BROWSER_VERIFICATION"] = "true"
    flags.loadFromEnv()
    // CLI overrides back to false
    flags.loadFromCLI({ "enable-browser": false })

    expect(flags.isEnabled(Feature.BROWSER_VERIFICATION)).toBe(false)
    expect(flags.dump()["browser_verification"].source).toBe("cli")

    delete process.env["ARGUS_FEATURE_BROWSER_VERIFICATION"]
  })

  test("dump returns all features with current state", () => {
    const dump = flags.dump()
    expect(Object.keys(dump).length).toBe(Object.values(Feature).length)
    for (const [key, val] of Object.entries(dump)) {
      expect(val).toHaveProperty("enabled")
      expect(val).toHaveProperty("source")
    }
  })
})
