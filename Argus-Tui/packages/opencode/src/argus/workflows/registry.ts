import { join } from "path"
import { loadAllWorkflows, loadWorkflowYaml } from "./loader"
import type { WorkflowDefinition } from "./types"
import { Capability } from "../shared/capabilities"

const _dirname = decodeURIComponent(new URL(".", import.meta.url).pathname)

export class WorkflowRegistry {
  private workflows = new Map<string, WorkflowDefinition>()
  private workflowsDir: string

  constructor(workflowsDir?: string) {
    this.workflowsDir = workflowsDir ?? join(_dirname, ".")
  }

  loadAll(): WorkflowDefinition[] {
    // Load into a temporary map so partial failure doesn't corrupt the live map
    const loaded = loadAllWorkflows(this.workflowsDir)
    const newMap = new Map<string, WorkflowDefinition>()
    for (const wf of loaded) {
      newMap.set(wf.name, wf)
    }
    this.workflows = newMap // atomic swap
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

    // Collect workflows in registration order (insertion order from the Map,
    // which preserves the order of loadAllWorkflows/readdirSync). When scores
    // are tied, prefer the workflow whose name sorts later alphabetically.
    // This is a deliberate tiebreaker that favors more specific/specialized
    // workflow names (e.g. "api_assessment_v2" beats "api_assessment").
    // Use >= for the score comparison so later-registered workflows with
    // equal scores replace earlier ones.
    for (const wf of this.workflows.values()) {
      const wfCaps = new Set(wf.phases.flatMap((p) => p.required_capabilities))
      const score = required.filter((c) => wfCaps.has(c)).length

      if (score >= bestScore && score > 0) {
        // On tie, prefer later-registered (more recently loaded/added) workflow.
        // This is deterministic because Map preserves insertion order.
        // `>=` ensures ties go to the later workflow rather than the first
        // alphabetically, which is less arbitrary than filename order.
        bestScore = score
        bestMatch = wf
      }
    }

    return bestMatch
  }

  addWorkflow(path: string): void {
    const wf = loadWorkflowYaml(path)
    this.workflows.set(wf.name, wf)
  }
}
