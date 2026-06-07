/**
 * ScanStore — Shared reactive state for active assessments.
 *
 * Uses SolidJS-style signals so TUI components can subscribe
 * to live progress updates during an assessment.
 *
 * The WorkflowRunner writes to this store; the scan dashboard
 * route reads from it reactively.
 */

import { createStore } from "solid-js/store"
import type { ProgressEvent } from "../shared/progress"

export interface ScanPhase {
  id: string
  name: string
  index: number
  total: number
  status: "pending" | "running" | "completed" | "failed"
  findings: number
  errors: string[]
}

export interface ScanState {
  target: string
  engagementId: string
  status: "idle" | "running" | "completed" | "failed"
  phases: ScanPhase[]
  totalFindings: number
  currentPhase: number
  log: string[]
  startTime: number
  durationMs: number
  analysisCurrent: number
  analysisTotal: number
}

const initialState: ScanState = {
  target: "",
  engagementId: "",
  status: "idle",
  phases: [],
  totalFindings: 0,
  currentPhase: 0,
  log: [],
  startTime: 0,
  durationMs: 0,
  analysisCurrent: 0,
  analysisTotal: 0,
}

// Module-level store — shared across all components
const [scanState, setScanState] = createStore<ScanState>({ ...initialState })

export function getScanState() {
  return scanState
}

export function initScan(target: string, engagementId: string) {
  setScanState({
    ...initialState,
    target,
    engagementId,
    status: "running",
    startTime: Date.now(),
  })
}

export function addPhase(phase: { id: string; name: string; index: number; total: number }) {
  setScanState("phases", (prev) => [
    ...prev,
    { ...phase, status: "running" as const, findings: 0, errors: [] },
  ])
  setScanState("currentPhase", phase.index)
}

export function completePhase(index: number, findings: number, errors: string[]) {
  setScanState("phases", index, "status", errors.length > 0 ? "failed" : "completed")
  setScanState("phases", index, "findings", findings)
  setScanState("phases", index, "errors", errors)
  setScanState("totalFindings", (prev) => prev + findings)
}

export function appendLog(msg: string) {
  setScanState("log", (prev) => [...prev, msg])
}

export function completeScan(success: boolean) {
  setScanState("status", success ? "completed" : "failed")
  setScanState("durationMs", Date.now() - scanState.startTime)
}

export function setTotalFindings(count: number) {
  setScanState("totalFindings", count)
}

export function resetScan() {
  setScanState({ ...initialState })
}

function findPhaseIndex(phaseId: string): number {
  return scanState.phases.findIndex((p) => p.id === phaseId)
}

export function handleProgressEvent(event: ProgressEvent) {
  switch (event.type) {
    case "phase_start":
      addPhase({ id: event.phaseId, name: event.name, index: scanState.phases.length, total: event.total })
      break
    case "phase_complete": {
      const ci = findPhaseIndex(event.phaseId)
      if (ci >= 0) completePhase(ci, event.findings, [])
      break
    }
    case "phase_error": {
      const ei = findPhaseIndex(event.phaseId)
      if (ei >= 0) completePhase(ei, 0, [event.error])
      break
    }
    case "analysis_progress":
      setScanState("analysisCurrent", event.current)
      setScanState("analysisTotal", event.total)
      break
    case "finding":
      appendLog(`[${event.severity}] ${event.title}`)
      break
    case "tool_start":
      appendLog(`Tool: ${event.tool}`)
      break
    case "tool_complete":
      appendLog(`Tool ${event.tool} complete: ${event.findings} finding(s)`)
      break
    case "scan_complete":
      setScanState("status", "completed")
      setScanState("durationMs", Date.now() - scanState.startTime)
      break
  }
}
