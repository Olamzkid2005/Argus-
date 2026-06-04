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

export interface ScanPhase {
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

export function addPhase(phase: { name: string; index: number; total: number }) {
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

export function resetScan() {
  setScanState({ ...initialState })
}
