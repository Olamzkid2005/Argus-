export interface ErrorHintData {
  tool: string
  errorId?: string
  summary: string
  detail: string
  remediation?: string
  hintCommand?: string
  docsUrl?: string
}

export type ProgressEvent =
  | { type: "phase_start"; phaseId: string; name: string; total: number; phaseIndex: number }
  | { type: "phase_replan"; count: number }
  | { type: "phase_complete"; phaseId: string; name: string; findings: number; status: string }
  | { type: "phase_error"; phaseId: string; name: string; error: string }
  | { type: "tool_start"; phaseId: string; tool: string }
  | { type: "tool_complete"; phaseId: string; tool: string; findings: number }
  | { type: "finding"; phaseId: string; severity: string; title: string }
  | { type: "analysis_progress"; current: number; total: number }
  | { type: "scan_complete"; totalFindings: number }
  | { type: "error_hint"; tool: string; summary: string; detail: string; remediation?: string; hintCommand?: string; docsUrl?: string; errorId?: string }
  // Verification progress events — wired through the pipeline for TUI display
  | { type: "verification_start"; phaseId: string; total: number }
  | { type: "verification_progress"; phaseId: string; current: number; total: number; findingTitle?: string; findingSubtype?: string }
  | { type: "verification_complete"; phaseId: string; passed: number; failed: number; total: number }
  // LLM planning analysis — surfaced to the TUI scan dashboard
  | { type: "llm_planning_start"; phase: "initial" | "replan" }
  | { type: "llm_planning_complete"; phase: "initial" | "replan"; targetAnalysis: string; suggestions: Array<{ capabilities: string[]; reasoning: string }>; llmModel: string; modelEnvDescription: string }
  | { type: "llm_planning_error"; phase: "initial" | "replan"; error: string }
  // LLM replan analysis — emitted when the LLM analyzes findings and suggests next steps
  | { type: "llm_replan_analysis"; label: string; reasoning: string; suggestedCapabilities: string[]; stopAssessment: boolean; llmModel: string }

export type ProgressCallback = (event: ProgressEvent) => void
