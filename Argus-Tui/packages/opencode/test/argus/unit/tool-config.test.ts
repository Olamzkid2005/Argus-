import { describe, expect, test } from "bun:test"
import { ToolConfig } from "../../../src/argus/config/tool-config"
import type { ToolSettings } from "../../../src/argus/config/tool-config"

describe("ToolConfig", () => {
  test("default config has all tools enabled", () => {
    const config = new ToolConfig()
    expect(config.isEnabled("nuclei")).toBe(true)
    expect(config.isEnabled("dalfox")).toBe(true)
    expect(config.isEnabled("any-tool")).toBe(true)
  })

  test("disabled tool excluded", () => {
    const config = new ToolConfig({ disabled: ["nuclei"] })
    expect(config.isEnabled("nuclei")).toBe(false)
    expect(config.isEnabled("dalfox")).toBe(true)
  })

  test("enabled list restricts to specified tools", () => {
    const config = new ToolConfig({ enabled: ["nuclei", "dalfox"] })
    expect(config.isEnabled("nuclei")).toBe(true)
    expect(config.isEnabled("dalfox")).toBe(true)
    expect(config.isEnabled("ffuf")).toBe(false)
  })

  test("disabled takes precedence over enabled", () => {
    const config = new ToolConfig({ enabled: ["nuclei", "dalfox"], disabled: ["dalfox"] })
    expect(config.isEnabled("nuclei")).toBe(true)
    expect(config.isEnabled("dalfox")).toBe(false)
  })

  test("custom path returned", () => {
    const config = new ToolConfig({ paths: { nuclei: "/custom/nuclei" } })
    expect(config.getPath("nuclei")).toBe("/custom/nuclei")
    expect(config.getPath("dalfox")).toBeUndefined()
  })

  test("custom timeout returned", () => {
    const config = new ToolConfig({ timeouts: { nuclei: 120 } })
    expect(config.getTimeout("nuclei")).toBe(120)
    expect(config.getTimeout("dalfox")).toBeUndefined()
  })

  describe("circuit breaker defaults", () => {
    test("returns default values when no config provided", () => {
      const config = new ToolConfig()
      const cb = config.getCircuitBreakerConfig()
      // Blocker 22: defaults relaxed from 5/300000 to 8/120000
      expect(cb.maxFailures).toBe(8)
      expect(cb.cooldownMs).toBe(120_000)
    })

    test("custom circuit breaker values", () => {
      const config = new ToolConfig({ circuit_breaker: { max_failures: 3, cooldown_ms: 60000 } })
      const cb = config.getCircuitBreakerConfig()
      expect(cb.maxFailures).toBe(3)
      expect(cb.cooldownMs).toBe(60000)
    })

    test("partial circuit breaker config merges with defaults", () => {
      const config = new ToolConfig({ circuit_breaker: { max_failures: 10 } })
      const cb = config.getCircuitBreakerConfig()
      expect(cb.maxFailures).toBe(10)
      expect(cb.cooldownMs).toBe(120_000)
    })
  })
})
