import { describe, expect, test, beforeEach } from "bun:test"
import { FeatureFlags, Feature, resetFeatureFlags } from "../../../../src/argus/config/feature-flags"

describe("FeatureFlags", () => {
  let flags: FeatureFlags

  beforeEach(() => {
    resetFeatureFlags()
    flags = new FeatureFlags()
  })

  test("autonomy features default to true", () => {
    expect(flags.isEnabled(Feature.WORKFLOW_REGISTRY)).toBe(true)
    expect(flags.isEnabled(Feature.ENGAGEMENT_STORE)).toBe(true)
    expect(flags.isEnabled(Feature.APPROVAL_GATES)).toBe(true)
    expect(flags.isEnabled(Feature.LLM_FINDING_ANALYSIS)).toBe(true)
    expect(flags.isEnabled(Feature.ENCRYPTION_AT_REST)).toBe(false)
  })

  test("DETERMINISTIC_FALLBACK defaults to true (auto-fallback)", () => {
    expect(flags.isEnabled(Feature.DETERMINISTIC_FALLBACK)).toBe(true)
  })

  test("constructor overrides enable features", () => {
    const f = new FeatureFlags({ [Feature.WORKFLOW_REGISTRY]: false })
    expect(f.isEnabled(Feature.WORKFLOW_REGISTRY)).toBe(false)
    expect(f.isEnabled(Feature.ENGAGEMENT_STORE)).toBe(true)
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
      [Feature.APPROVAL_GATES]: true,
    })
    expect(f.allEnabled(Feature.WORKFLOW_REGISTRY, Feature.ENGAGEMENT_STORE)).toBe(true)
    expect(f.allEnabled(Feature.WORKFLOW_REGISTRY, Feature.ENCRYPTION_AT_REST)).toBe(false)
  })

  test("anyEnabled returns true when any feature is enabled", () => {
    const f = new FeatureFlags({ [Feature.WORKFLOW_REGISTRY]: false, [Feature.ENGAGEMENT_STORE]: false })
    expect(f.anyEnabled(Feature.WORKFLOW_REGISTRY, Feature.ENGAGEMENT_STORE)).toBe(false)
    expect(f.anyEnabled(Feature.ENGAGEMENT_STORE, Feature.APPROVAL_GATES)).toBe(true)
  })

  test("loadFromEnv reads ARGUS_FEATURE_* environment variables", () => {
    process.env["ARGUS_FEATURE_ENCRYPTION_AT_REST"] = "1"
    flags.loadFromEnv()
    expect(flags.isEnabled(Feature.ENCRYPTION_AT_REST)).toBe(true)
    expect(flags.isEnabled(Feature.ENGAGEMENT_STORE)).toBe(true)
    delete process.env["ARGUS_FEATURE_ENCRYPTION_AT_REST"]
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
