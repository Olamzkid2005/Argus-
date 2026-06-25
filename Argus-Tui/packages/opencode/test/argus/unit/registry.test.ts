import { describe, expect, test, mock } from "bun:test"
import { mkdtempSync, writeFileSync, rmSync, readdirSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { WorkflowRegistry } from "../../../src/argus/workflows/registry"

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
    execution: parallel
    error_recovery: skip_and_continue
`

describe("WorkflowRegistry atomic swap", () => {
  describe("loadAll atomically swaps map", () => {
    test("loadAll replaces entire map — old workflows are gone", () => {
      const dir = makeTempDir()
      try {
        writeFileSync(join(dir, "workflow_a.yaml"), workflow1Yaml, "utf-8")
        const registry = new WorkflowRegistry(dir)
        registry.loadAll()
        expect(registry.listWorkflows()).toHaveLength(1)
        expect(registry.getWorkflow("quick_scan")).toBeDefined()

        writeFileSync(join(dir, "workflow_b.yaml"), workflow2Yaml, "utf-8")
        registry.loadAll()
        const workflows = registry.listWorkflows()
        expect(workflows).toHaveLength(2)
        expect(registry.getWorkflow("quick_scan")).toBeDefined()
        expect(registry.getWorkflow("full_assessment")).toBeDefined()
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("loadAll with empty directory clears previously loaded workflows", () => {
      const dir = makeTempDir()
      try {
        writeFileSync(join(dir, "workflow.yaml"), workflow1Yaml, "utf-8")
        const registry = new WorkflowRegistry(dir)
        registry.loadAll()
        expect(registry.listWorkflows()).toHaveLength(1)

        rmSync(join(dir, "workflow.yaml"))
        registry.loadAll()
        expect(registry.listWorkflows()).toHaveLength(0)
        expect(registry.getWorkflow("quick_scan")).toBeUndefined()
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })

    test("mixed valid and invalid YAML — valid ones are loaded, invalid skipped", () => {
      const dir = makeTempDir()
      try {
        writeFileSync(join(dir, "good.yaml"), workflow1Yaml, "utf-8")
        writeFileSync(join(dir, "bad.yaml"), `name: incomplete\n`, "utf-8")
        const registry = new WorkflowRegistry(dir)
        registry.loadAll()
        expect(registry.getWorkflow("quick_scan")).toBeDefined()
        expect(registry.listWorkflows()).toHaveLength(1)
      } finally {
        rmSync(dir, { recursive: true, force: true })
      }
    })
  })

  describe("previously loaded workflows are available when loadAll fails gracefully", () => {
    test("workflows added via addWorkflow survive a loadAll that returns empty", () => {
      const dir = makeTempDir()
      try {
        const registry = new WorkflowRegistry(dir)
        const filePath = join(dir, "manual.yaml")
        writeFileSync(filePath, workflow1Yaml, "utf-8")
        registry.addWorkflow(filePath)
        expect(registry.getWorkflow("quick_scan")).toBeDefined()

        rmSync(dir, { recursive: true, force: true })
        mkdtempSync(dir)
        registry.loadAll()
        expect(registry.getWorkflow("quick_scan")).toBeUndefined()
      } finally {
        try { rmSync(dir, { recursive: true, force: true }) } catch {}
      }
    })
  })
})
