import { describe, expect, test } from "bun:test"
import { mkdtempSync, writeFileSync, rmSync } from "fs"
import { join } from "path"
import { tmpdir } from "os"
import { loadWorkflowYaml, loadAllWorkflows } from "../../../../src/argus/workflows/loader"

function makeTempDir(): string {
  const dir = mkdtempSync(join(tmpdir(), "argus-test-"))
  return dir
}

const validYaml = `name: test_workflow
label: Test Workflow
version: 1
phases:
  - name: recon
    required_capabilities:
      - web_recon
      - port_scanning
    execution: parallel
    error_recovery: skip_and_continue
  - name: exploit
    required_capabilities:
      - vulnerability_scanning
    execution: sequential
    error_recovery: fail_fast
`

describe("loadWorkflowYaml", () => {
  test("Loads a valid workflow YAML correctly (name, label, version, phases)", () => {
    const dir = makeTempDir()
    try {
      const filePath = join(dir, "test.yaml")
      writeFileSync(filePath, validYaml, "utf-8")
      const workflow = loadWorkflowYaml(filePath)
      expect(workflow.name).toBe("test_workflow")
      expect(workflow.label).toBe("Test Workflow")
      expect(workflow.version).toBe(1)
      expect(workflow.phases).toHaveLength(2)
      expect(workflow.phases[0].name).toBe("recon")
      expect(workflow.phases[1].name).toBe("exploit")
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  test("Throws on missing 'name' field", () => {
    const dir = makeTempDir()
    try {
      const filePath = join(dir, "no-name.yaml")
      writeFileSync(filePath, `label: No Name\nphases: []\n`, "utf-8")
      expect(() => loadWorkflowYaml(filePath)).toThrow(/missing 'name' or 'phases'/)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  test("Throws on missing 'phases' array", () => {
    const dir = makeTempDir()
    try {
      const filePath = join(dir, "no-phases.yaml")
      writeFileSync(filePath, `name: no_phases\nlabel: No Phases\n`, "utf-8")
      expect(() => loadWorkflowYaml(filePath)).toThrow(/missing 'name' or 'phases'/)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  test("Throws on unknown capability in required_capabilities", () => {
    const dir = makeTempDir()
    try {
      const filePath = join(dir, "bad-cap.yaml")
      writeFileSync(filePath, `name: bad_cap
label: Bad Cap
version: 1
phases:
  - name: test
    required_capabilities:
      - unknown_cap_xyz
    execution: parallel
    error_recovery: skip_and_continue
`, "utf-8")
      expect(() => loadWorkflowYaml(filePath)).toThrow(/Unknown capability/)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  test("Throws on invalid execution mode", () => {
    const dir = makeTempDir()
    try {
      const filePath = join(dir, "bad-exec.yaml")
      writeFileSync(filePath, `name: bad_exec
label: Bad Exec
version: 1
phases:
  - name: test
    required_capabilities:
      - web_recon
    execution: invalid_mode
    error_recovery: skip_and_continue
`, "utf-8")
      expect(() => loadWorkflowYaml(filePath)).toThrow(/Invalid execution mode/)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  test("Throws on invalid error_recovery", () => {
    const dir = makeTempDir()
    try {
      const filePath = join(dir, "bad-recovery.yaml")
      writeFileSync(filePath, `name: bad_recovery
label: Bad Recovery
version: 1
phases:
  - name: test
    required_capabilities:
      - web_recon
    execution: parallel
    error_recovery: invalid_recovery
`, "utf-8")
      expect(() => loadWorkflowYaml(filePath)).toThrow(/Invalid error_recovery/)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  test("Accepts valid error_recovery values", () => {
    const dir = makeTempDir()
    try {
      for (const recovery of ["retry_once_then_skip", "skip_and_continue", "fail_fast"]) {
        const filePath = join(dir, `recovery-${recovery}.yaml`)
        writeFileSync(filePath, `name: recovery_${recovery}
label: Recovery ${recovery}
version: 1
phases:
  - name: test
    required_capabilities:
      - web_recon
    execution: parallel
    error_recovery: ${recovery}
`, "utf-8")
        const workflow = loadWorkflowYaml(filePath)
        expect(workflow.name).toBe(`recovery_${recovery}`)
      }
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })
})

describe("loadAllWorkflows", () => {
  test("Loads all .yaml and .yml files from a directory", () => {
    const dir = makeTempDir()
    try {
      writeFileSync(join(dir, "a.yaml"), validYaml, "utf-8")
      writeFileSync(join(dir, "b.yml"), validYaml, "utf-8")
      const workflows = loadAllWorkflows(dir)
      expect(workflows).toHaveLength(2)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  test("Skips non-YAML files", () => {
    const dir = makeTempDir()
    try {
      writeFileSync(join(dir, "workflow.yaml"), validYaml, "utf-8")
      writeFileSync(join(dir, "readme.txt"), "not yaml", "utf-8")
      writeFileSync(join(dir, "data.json"), "{}", "utf-8")
      const workflows = loadAllWorkflows(dir)
      expect(workflows).toHaveLength(1)
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  test("Handles empty directory gracefully", () => {
    const dir = makeTempDir()
    try {
      const workflows = loadAllWorkflows(dir)
      expect(workflows).toEqual([])
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  test("Logs error for invalid YAML files but continues loading others", () => {
    const dir = makeTempDir()
    try {
      writeFileSync(join(dir, "good.yaml"), validYaml, "utf-8")
      writeFileSync(join(dir, "bad.yaml"), `name: bad\nphases: not_an_array\n`, "utf-8")
      const workflows = loadAllWorkflows(dir)
      expect(workflows).toHaveLength(1)
      expect(workflows[0].name).toBe("test_workflow")
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })
})
