import { readFileSync, readdirSync } from "fs"
import { join, extname } from "path"
import YAML from "yaml"
import type { WorkflowDefinition } from "./types"
import { Capability } from "../shared/capabilities"

export function loadWorkflowYaml(path: string): WorkflowDefinition {
  const content = readFileSync(path, "utf-8")
  const parsed = YAML.parse(content)

  const workflow = parsed as WorkflowDefinition

  if (!workflow.name || !workflow.phases || !Array.isArray(workflow.phases)) {
    throw new Error(`Invalid workflow YAML: missing 'name' or 'phases' in ${path}`)
  }

  for (const phase of workflow.phases) {
    if (!phase.required_capabilities || !Array.isArray(phase.required_capabilities)) {
      throw new Error(`Phase '${phase.name}' in ${path} missing required_capabilities`)
    }

    for (const cap of phase.required_capabilities) {
      if (!Object.values(Capability).includes(cap as Capability)) {
        throw new Error(`Unknown capability '${cap}' in phase '${phase.name}' — not in Capability enum`)
      }
    }

    if (!phase.execution || !["parallel", "sequential"].includes(phase.execution)) {
      throw new Error(`Invalid execution mode '${phase.execution}' in phase '${phase.name}'`)
    }

    if (phase.error_recovery && !["retry_once_then_skip", "skip_and_continue", "fail_fast"].includes(phase.error_recovery)) {
      throw new Error(`Invalid error_recovery '${phase.error_recovery}' in phase '${phase.name}'`)
    }
  }

  return workflow
}

export function loadAllWorkflows(workflowsDir: string): WorkflowDefinition[] {
  const workflows: WorkflowDefinition[] = []
  let files: string[]

  try {
    files = readdirSync(workflowsDir)
  } catch {
    process.stderr.write(`Warning: workflows directory not found at '${workflowsDir}'\n`)
    return workflows
  }

  for (const file of files) {
    if (extname(file) === ".yaml" || extname(file) === ".yml") {
      const fullPath = join(workflowsDir, file)
      try {
        const workflow = loadWorkflowYaml(fullPath)
        workflows.push(workflow)
      } catch {
        // Not all YAMLs in the workflows dir are workflows —
        // tool-definitions.yaml and approval-policies.yaml use different schemas.
        // Skip silently — this is expected.
      }
    }
  }

  return workflows
}
