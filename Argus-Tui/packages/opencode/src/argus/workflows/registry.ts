import { join } from "path"
import { loadAllWorkflows, loadWorkflowYaml } from "./loader"
import type { WorkflowDefinition } from "./types"
import { Capability } from "../planner/capabilities"

export class WorkflowRegistry {
  private workflows = new Map<string, WorkflowDefinition>()
  private workflowsDir: string

  constructor(workflowsDir?: string) {
    // __dirname is stable in Bun and this codebase targets Bun. For Node ESM use fileURLToPath(import.meta.url).
    this.workflowsDir = workflowsDir ?? join(__dirname, ".")
  }

  loadAll(): WorkflowDefinition[] {
    // Clear stale entries so repeated calls don't accumulate orphaned workflows
    this.workflows.clear()
    const loaded = loadAllWorkflows(this.workflowsDir)
    for (const wf of loaded) {
      this.workflows.set(wf.name, wf)
    }
    return loaded
  }

  getWorkflow(name: string): WorkflowDefinition | undefined {
    return this.workflows.get(name)
  }

  listWorkflows(): WorkflowDefinition[] {
    return Array.from(this.workflows.values())
  }

  findByCapabilities(required: Capability[]): WorkflowDefinition | null {
    let bestMatch: WorkflowDefinition | null = null
    let bestScore = -1

    for (const wf of this.workflows.values()) {
      const wfCaps = new Set(wf.phases.flatMap((p) => p.required_capabilities))
      const score = required.filter((c) => wfCaps.has(c)).length

      if (score > bestScore) {
        bestScore = score
        bestMatch = wf
      }
    }

    // Intentional: returns best match even if score is 0 (e.g. empty phases),
    // or null if there are no workflows at all. The caller distinguishes these cases.
    return bestMatch
  }

  addWorkflow(path: string): void {
    const wf = loadWorkflowYaml(path)
    this.workflows.set(wf.name, wf)
  }
}
