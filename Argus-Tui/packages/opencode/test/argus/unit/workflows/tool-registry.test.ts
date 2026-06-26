import { describe, expect, test } from "bun:test"
import { mkdtempSync, writeFileSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { ToolRegistry } from "../../../../src/argus/workflows/tool-registry"
import { Capability } from "../../../../src/argus/planner/capabilities"

function makeTempDir(): string {
  return mkdtempSync(join(tmpdir(), "argus-tool-reg-"))
}

const validToolsYaml = `tools:
  - name: scanner
    label: Vulnerability Scanner
    capabilities:
      - vulnerability_scanning
      - port_scanning
    requires_auth: false
    destructive: false
    supports_api: true
    supports_web: true
    timeout_seconds: 300
    scoring:
      confidence_score: 90
      coverage_score: 85

  - name: recon_tool
    label: Recon Tool
    capabilities:
      - web_recon
      - technology_detection
    requires_auth: false
    destructive: false
    supports_api: true
    supports_web: true
    timeout_seconds: 120
    scoring:
      confidence_score: 80
      coverage_score: 75

  - name: auth_tester
    label: Auth Tester
    capabilities:
      - auth_detection
      - credential_analysis
    requires_auth: true
    destructive: false
    supports_api: true
    supports_web: false
    timeout_seconds: 200
    scoring:
      confidence_score: 85
      coverage_score: 80
`

describe("ToolRegistry", () => {
  describe("load()", () => {
    test("parses tool definitions correctly", () => {
      const dir = makeTempDir()
      try {
        const filePath = join(dir, "tools.yaml")
        writeFileSync(filePath, validToolsYaml, "utf-8")
        const registry = new ToolRegistry()
        registry.load(filePath)
        const tools = registry.listTools()
        expect(tools).toHaveLength(3)
        expect(tools.map((t) => t.name).sort()).toEqual(["auth_tester", "recon_tool", "scanner"])
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("throws on unknown capability", () => {
      const dir = makeTempDir()
      try {
        const filePath = join(dir, "bad-tools.yaml")
        writeFileSync(filePath, `tools:
  - name: bad_tool
    label: Bad Tool
    capabilities:
      - unknown_cap_xyz
    requires_auth: false
    destructive: false
    supports_api: true
    supports_web: true
    timeout_seconds: 30
`, "utf-8")
        const registry = new ToolRegistry()
        expect(() => registry.load(filePath)).toThrow(/unknown capability/)
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })
  })

  describe("getToolsByCapability()", () => {
    test("returns empty array for unknown capability", () => {
      const dir = makeTempDir()
      try {
        const filePath = join(dir, "tools.yaml")
        writeFileSync(filePath, validToolsYaml, "utf-8")
        const registry = new ToolRegistry()
        registry.load(filePath)
        const tools = registry.getToolsByCapability(Capability.SQLI_DETECTION)
        expect(tools).toEqual([])
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("returns tools for a registered capability", () => {
      const dir = makeTempDir()
      try {
        const filePath = join(dir, "tools.yaml")
        writeFileSync(filePath, validToolsYaml, "utf-8")
        const registry = new ToolRegistry()
        registry.load(filePath)
        const tools = registry.getToolsByCapability(Capability.VULNERABILITY_SCANNING)
        expect(tools).toHaveLength(1)
        expect(tools[0].name).toBe("scanner")
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })
  })

  describe("getCapabilities()", () => {
    test("returns capabilities for a known tool, empty array for unknown", () => {
      const dir = makeTempDir()
      try {
        const filePath = join(dir, "tools.yaml")
        writeFileSync(filePath, validToolsYaml, "utf-8")
        const registry = new ToolRegistry()
        registry.load(filePath)
        const caps = registry.getCapabilities("scanner")
        expect(caps).toEqual(["vulnerability_scanning", "port_scanning"])
        expect(registry.getCapabilities("nonexistent")).toEqual([])
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })
  })

  describe("getTool()", () => {
    test("returns tool definition, undefined for unknown", () => {
      const dir = makeTempDir()
      try {
        const filePath = join(dir, "tools.yaml")
        writeFileSync(filePath, validToolsYaml, "utf-8")
        const registry = new ToolRegistry()
        registry.load(filePath)
        const tool = registry.getTool("scanner")
        expect(tool).toBeDefined()
        expect(tool!.label).toBe("Vulnerability Scanner")
        expect(registry.getTool("nonexistent")).toBeUndefined()
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })
  })

  describe("listTools()", () => {
    test("returns all loaded tools", () => {
      const dir = makeTempDir()
      try {
        const filePath = join(dir, "tools.yaml")
        writeFileSync(filePath, validToolsYaml, "utf-8")
        const registry = new ToolRegistry()
        registry.load(filePath)
        const tools = registry.listTools()
        expect(tools).toHaveLength(3)
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })
  })

  describe("findBestTools()", () => {
    test("scores and ranks tools by confidence + coverage", () => {
      const dir = makeTempDir()
      try {
        const filePath = join(dir, "tools.yaml")
        writeFileSync(filePath, validToolsYaml, "utf-8")
        const registry = new ToolRegistry()
        registry.load(filePath)

        const tools = registry.findBestTools(
          [Capability.WEB_RECON, Capability.TECHNOLOGY_DETECTION],
          "web_app",
        )
        expect(tools).toHaveLength(1)
        expect(tools[0].name).toBe("recon_tool")
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("returns empty array when no capabilities match", () => {
      const dir = makeTempDir()
      try {
        const filePath = join(dir, "tools.yaml")
        writeFileSync(filePath, validToolsYaml, "utf-8")
        const registry = new ToolRegistry()
        registry.load(filePath)
        const tools = registry.findBestTools([Capability.API_PROBING], "api")
        expect(tools).toEqual([])
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("deduplicates tools that appear under multiple capabilities", () => {
      const dir = makeTempDir()
      try {
        const multiCapsYaml = `tools:
  - name: multi_tool
    label: Multi Cap Tool
    capabilities:
      - vulnerability_scanning
      - port_scanning
      - web_recon
    requires_auth: false
    destructive: false
    supports_api: true
    supports_web: true
    timeout_seconds: 300
    scoring:
      confidence_score: 90
      coverage_score: 85

  - name: other_tool
    label: Other Tool
    capabilities:
      - technology_detection
    requires_auth: false
    destructive: false
    supports_api: true
    supports_web: true
    timeout_seconds: 120
    scoring:
      confidence_score: 70
      coverage_score: 65
`
        const filePath = join(dir, "multi-tools.yaml")
        writeFileSync(filePath, multiCapsYaml, "utf-8")
        const registry = new ToolRegistry()
        registry.load(filePath)
        const tools = registry.findBestTools(
          [Capability.VULNERABILITY_SCANNING, Capability.PORT_SCANNING, Capability.WEB_RECON],
          "web_app",
        )
        expect(tools).toHaveLength(1)
        expect(tools[0].name).toBe("multi_tool")
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })
  })

  describe("selectBest() — costFilter", () => {
    const costToolsYaml = `tools:
  - name: cheap_scanner
    label: Cheap Scanner
    capabilities:
      - vulnerability_scanning
    requires_auth: false
    destructive: false
    supports_api: true
    supports_web: true
    timeout_seconds: 300
    cost: low
    scoring:
      confidence_score: 80
      coverage_score: 75

  - name: medium_scanner
    label: Medium Scanner
    capabilities:
      - vulnerability_scanning
    requires_auth: false
    destructive: false
    supports_api: true
    supports_web: true
    timeout_seconds: 300
    cost: medium
    scoring:
      confidence_score: 85
      coverage_score: 80

  - name: expensive_scanner
    label: Expensive Scanner
    capabilities:
      - vulnerability_scanning
    requires_auth: false
    destructive: false
    supports_api: true
    supports_web: true
    timeout_seconds: 300
    cost: high
    scoring:
      confidence_score: 95
      coverage_score: 90

  - name: exclusive_high
    label: Exclusive High Cost Tool
    capabilities:
      - port_scanning
    requires_auth: false
    destructive: false
    supports_api: true
    supports_web: true
    timeout_seconds: 300
    cost: high
    scoring:
      confidence_score: 70
      coverage_score: 65
`

    test("returns all tools when costFilter is undefined (backward compat)", () => {
      const dir = makeTempDir()
      try {
        const filePath = join(dir, "cost-tools.yaml")
        writeFileSync(filePath, costToolsYaml, "utf-8")
        const registry = new ToolRegistry()
        registry.load(filePath)
        const tools = registry.selectBest([Capability.VULNERABILITY_SCANNING], "web_app")
        expect(tools).toHaveLength(3)
        const names = tools.map((t) => t.name)
        expect(names).toContain("cheap_scanner")
        expect(names).toContain("medium_scanner")
        expect(names).toContain("expensive_scanner")
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("returns all tools when costFilter is \"all\"", () => {
      const dir = makeTempDir()
      try {
        const filePath = join(dir, "cost-tools.yaml")
        writeFileSync(filePath, costToolsYaml, "utf-8")
        const registry = new ToolRegistry()
        registry.load(filePath)
        const tools = registry.selectBest([Capability.VULNERABILITY_SCANNING], "web_app", undefined, "all")
        expect(tools).toHaveLength(3)
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("filters out high-cost tools when costFilter is \"no_high\"", () => {
      const dir = makeTempDir()
      try {
        const filePath = join(dir, "cost-tools.yaml")
        writeFileSync(filePath, costToolsYaml, "utf-8")
        const registry = new ToolRegistry()
        registry.load(filePath)
        const tools = registry.selectBest([Capability.VULNERABILITY_SCANNING], "web_app", undefined, "no_high")
        expect(tools).toHaveLength(2)
        const names = tools.map((t) => t.name)
        expect(names).toContain("cheap_scanner")
        expect(names).toContain("medium_scanner")
        expect(names).not.toContain("expensive_scanner")
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("filters to only low-cost tools when costFilter is \"low_only\"", () => {
      const dir = makeTempDir()
      try {
        const filePath = join(dir, "cost-tools.yaml")
        writeFileSync(filePath, costToolsYaml, "utf-8")
        const registry = new ToolRegistry()
        registry.load(filePath)
        const tools = registry.selectBest([Capability.VULNERABILITY_SCANNING], "web_app", undefined, "low_only")
        expect(tools).toHaveLength(1)
        expect(tools[0].name).toBe("cheap_scanner")
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("safety net: keeps high-cost tool when it's the only tool for a capability", () => {
      const dir = makeTempDir()
      try {
        const filePath = join(dir, "cost-tools.yaml")
        writeFileSync(filePath, costToolsYaml, "utf-8")
        const registry = new ToolRegistry()
        registry.load(filePath)
        // port_scanning only has exclusive_high (high cost) — should be kept despite "no_high"
        const tools = registry.selectBest([Capability.PORT_SCANNING], "web_app", undefined, "no_high")
        expect(tools).toHaveLength(1)
        expect(tools[0].name).toBe("exclusive_high")
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("safety net: keeps high-cost tool when capability would be left empty (low_only)", () => {
      const dir = makeTempDir()
      try {
        const filePath = join(dir, "cost-tools.yaml")
        writeFileSync(filePath, costToolsYaml, "utf-8")
        const registry = new ToolRegistry()
        registry.load(filePath)
        // port_scanning only has exclusive_high (high cost) — must be kept despite "low_only"
        const tools = registry.selectBest([Capability.PORT_SCANNING], "web_app", undefined, "low_only")
        expect(tools).toHaveLength(1)
        expect(tools[0].name).toBe("exclusive_high")
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("safety net does not activate when other tools cover the capability", () => {
      const dir = makeTempDir()
      try {
        const filePath = join(dir, "cost-tools.yaml")
        writeFileSync(filePath, costToolsYaml, "utf-8")
        const registry = new ToolRegistry()
        registry.load(filePath)
        // vulnerability_scanning has low, medium, and high tools
        // "no_high" should remove expensive_scanner since cheap/medium still cover it
        const tools = registry.selectBest([Capability.VULNERABILITY_SCANNING], "web_app", undefined, "no_high")
        expect(tools).toHaveLength(2)
        expect(tools.map((t) => t.name)).not.toContain("expensive_scanner")
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })
  })
})
