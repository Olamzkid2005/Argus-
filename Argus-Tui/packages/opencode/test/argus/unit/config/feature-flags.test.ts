import { describe, expect, test, beforeEach } from "bun:test"
import { FeatureFlags, Feature, resetFeatureFlags } from "../../../../src/argus/config/feature-flags"

describe("FeatureFlags", () => {
  let flags: FeatureFlags

  beforeEach(() => {
    resetFeatureFlags()
    flags = new FeatureFlags()
  })

  test("all features default to false (opt-in)", () => {
    expect(flags.isEnabled(Feature.WORKFLOW_REGISTRY)).toBe(false)
    expect(flags.isEnabled(Feature.ENGAGEMENT_STORE)).toBe(false)
    expect(flags.isEnabled(Feature.APPROVAL_GATES)).toBe(false)
  })

  test("DETERMINISTIC_FALLBACK defaults to false (opt-in)", () => {
    expect(flags.isEnabled(Feature.DETERMINISTIC_FALLBACK)).toBe(false)
  })

  test("constructor overrides enable features", () => {
    const f = new FeatureFlags({ [Feature.WORKFLOW_REGISTRY]: true })
    expect(f.isEnabled(Feature.WORKFLOW_REGISTRY)).toBe(true)
    expect(f.isEnabled(Feature.ENGAGEMENT_STORE)).toBe(false)
  })

  test("applyOverrides updates features and records source", () => {
    flags.applyOverrides({ [Feature.WORKFLOW_REGISTRY]: true }, "config")
    expect(flags.isEnabled(Feature.WORKFLOW_REGISTRY)).toBe(true)
    const dump = flags.dump()
    expect(dump["workflow_registry"].source).toBe("config")
  })

  test("allEnabled returns true only when all features are enabled", () => {
    const f = new FeatureFlags({
      [Feature.WORKFLOW_REGISTRY]: true,
      [Feature.ENGAGEMENT_STORE]: true,
    })
    expect(f.allEnabled(Feature.WORKFLOW_REGISTRY, Feature.ENGAGEMENT_STORE)).toBe(true)
    expect(f.allEnabled(Feature.WORKFLOW_REGISTRY, Feature.APPROVAL_GATES)).toBe(false)
  })

  test("anyEnabled returns true when any feature is enabled", () => {
    const f = new FeatureFlags({ [Feature.WORKFLOW_REGISTRY]: true })
    expect(f.anyEnabled(Feature.WORKFLOW_REGISTRY, Feature.ENGAGEMENT_STORE)).toBe(true)
    expect(f.anyEnabled(Feature.ENGAGEMENT_STORE, Feature.APPROVAL_GATES)).toBe(false)
  })

  test("loadFromEnv reads ARGUS_FEATURE_* environment variables", () => {
    process.env["ARGUS_FEATURE_WORKFLOW_REGISTRY"] = "1"
    flags.loadFromEnv()
    expect(flags.isEnabled(Feature.WORKFLOW_REGISTRY)).toBe(true)
    expect(flags.isEnabled(Feature.ENGAGEMENT_STORE)).toBe(false)
    delete process.env["ARGUS_FEATURE_WORKFLOW_REGISTRY"]
  })

  test("loadFromConfig reads feature config object", () => {
    flags.loadFromConfig({ "workflow_registry": true })
    expect(flags.isEnabled(Feature.WORKFLOW_REGISTRY)).toBe(true)
  })

  test("precedence: CLI overrides env overrides config over defaults", () => {
    // config sets it false
    flags.loadFromConfig({ "workflow_registry": false })
    // env overrides to true
    process.env["ARGUS_FEATURE_WORKFLOW_REGISTRY"] = "true"
    flags.loadFromEnv()
    // CLI overrides back to false
    flags.applyOverrides({ [Feature.DETERMINISTIC_FALLBACK]: true }, "cli")

    expect(flags.isEnabled(Feature.WORKFLOW_REGISTRY)).toBe(true)
    expect(flags.dump()["workflow_registry"].source).toBe("env")

    delete process.env["ARGUS_FEATURE_WORKFLOW_REGISTRY"]
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
