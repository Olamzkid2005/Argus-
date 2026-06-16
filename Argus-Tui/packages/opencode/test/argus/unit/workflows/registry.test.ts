import { describe, expect, test } from "bun:test"
import { mkdtempSync, writeFileSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { WorkflowRegistry } from "../../../../src/argus/workflows/registry"
import { Capability } from "../../../../src/argus/planner/capabilities"

function makeTempDir(): string {
  return mkdtempSync(join(tmpdir(), "argus-registry-test-"))
}

const workflow1Yaml = `name: quick_scan
label: Quick Scan
version: 1
phases:
  - name: recon
    required_capabilities:
      - web_recon
      - port_scanning
    execution: parallel
    error_recovery: skip_and_continue
`

const workflow2Yaml = `name: full_assessment
label: Full Assessment
version: 2
phases:
  - name: recon
    required_capabilities:
      - web_recon
      - port_scanning
      - technology_detection
    execution: parallel
    error_recovery: skip_and_continue
  - name: exploit
    required_capabilities:
      - vulnerability_scanning
      - sqli_detection
    execution: sequential
    error_recovery: fail_fast
`

describe("WorkflowRegistry", () => {
  describe("loadAll()", () => {
    test("loads all workflows from directory", () => {
      const dir = makeTempDir()
      try {
        writeFileSync(join(dir, "quick_scan.yaml"), workflow1Yaml, "utf-8")
        writeFileSync(join(dir, "full_assessment.yaml"), workflow2Yaml, "utf-8")
        const registry = new WorkflowRegistry(dir)
        const loaded = registry.loadAll()
        expect(loaded).toHaveLength(2)
        expect(loaded.map((w) => w.name).sort()).toEqual(["full_assessment", "quick_scan"])
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })
  })

  describe("getWorkflow(name)", () => {
    test("returns undefined for unknown workflow", () => {
      const dir = makeTempDir()
      try {
        const registry = new WorkflowRegistry(dir)
        expect(registry.getWorkflow("nonexistent")).toBeUndefined()
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("returns workflow after loading", () => {
      const dir = makeTempDir()
      try {
        writeFileSync(join(dir, "quick_scan.yaml"), workflow1Yaml, "utf-8")
        const registry = new WorkflowRegistry(dir)
        registry.loadAll()
        const wf = registry.getWorkflow("quick_scan")
        expect(wf).toBeDefined()
        expect(wf!.label).toBe("Quick Scan")
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })
  })

  describe("listWorkflows()", () => {
    test("returns all loaded workflows", () => {
      const dir = makeTempDir()
      try {
        writeFileSync(join(dir, "quick_scan.yaml"), workflow1Yaml, "utf-8")
        writeFileSync(join(dir, "full_assessment.yaml"), workflow2Yaml, "utf-8")
        const registry = new WorkflowRegistry(dir)
        registry.loadAll()
        const list = registry.listWorkflows()
        expect(list).toHaveLength(2)
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })
  })

  describe("findByCapabilities()", () => {
    test("returns best matching workflow by capability coverage", () => {
      const dir = makeTempDir()
      try {
        writeFileSync(join(dir, "quick_scan.yaml"), workflow1Yaml, "utf-8")
        writeFileSync(join(dir, "full_assessment.yaml"), workflow2Yaml, "utf-8")
        const registry = new WorkflowRegistry(dir)
        registry.loadAll()
        const best = registry.findByCapabilities([
          Capability.WEB_RECON,
          Capability.PORT_SCANNING,
          Capability.TECHNOLOGY_DETECTION,
          Capability.VULNERABILITY_SCANNING,
        ])
        expect(best).toBeDefined()
        expect(best!.name).toBe("full_assessment")
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("returns null when no workflows loaded", () => {
      const dir = makeTempDir()
      try {
        const registry = new WorkflowRegistry(dir)
        const result = registry.findByCapabilities([Capability.WEB_RECON])
        expect(result).toBeNull()
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("returns null when no capabilities match any workflow (score must be > 0)", () => {
      const dir = makeTempDir()
      try {
        writeFileSync(join(dir, "quick_scan.yaml"), workflow1Yaml, "utf-8")
        const registry = new WorkflowRegistry(dir)
        registry.loadAll()
        const result = registry.findByCapabilities([Capability.SQLI_DETECTION, Capability.API_PROBING])
        expect(result).toBeNull()
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })
  })

  describe("addWorkflow(path)", () => {
    test("loads a workflow from a specific file path", () => {
      const dir = makeTempDir()
      try {
        const filePath = join(dir, "custom.yaml")
        writeFileSync(filePath, workflow1Yaml, "utf-8")
        const registry = new WorkflowRegistry(dir)
        registry.addWorkflow(filePath)
        const wf = registry.getWorkflow("quick_scan")
        expect(wf).toBeDefined()
        expect(wf!.label).toBe("Quick Scan")
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })
  })
})
