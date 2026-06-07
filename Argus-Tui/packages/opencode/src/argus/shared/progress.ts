export type ProgressEvent =
  | { type: "phase_start"; phaseId: string; name: string; total: number }
  | { type: "phase_complete"; phaseId: string; name: string; findings: number; status: string }
  | { type: "phase_error"; phaseId: string; name: string; error: string }
  | { type: "tool_start"; phaseId: string; tool: string }
  | { type: "tool_complete"; phaseId: string; tool: string; findings: number }
  | { type: "finding"; phaseId: string; severity: string; title: string }
  | { type: "analysis_progress"; current: number; total: number }
  | { type: "scan_complete"; totalFindings: number }

export type ProgressCallback = (event: ProgressEvent) => void
