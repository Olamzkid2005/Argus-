/**
 * ScanStore — Engagement-scoped reactive state for assessments.
 *
 * Maintains separate ScanState per engagementId so concurrent assessments
 * don't contaminate each other's progress. The TUI reads from the
 * currently active engagement's state via getScanState().
 */

import { createStore } from "solid-js/store"
import type { ErrorHintData, ProgressEvent } from "../shared/progress"

export interface ScanPhase {
  id: string
  name: string
  index: number
  total: number
  status: "pending" | "running" | "completed" | "partial" | "failed"
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
  errorHints: ErrorHintData[]
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
  errorHints: [] as ErrorHintData[],
}

const [scanState, setScanState] = createStore<ScanState>({ ...initialState })

const savedStates = new Map<string, ScanState>()

let activeEngagementId: string | null = null
let _processingLock: string | null = null
const _pendingQueue: Array<{ event: ProgressEvent; engagementId?: string }> = []

function snapshot(): ScanState {
  return {
    target: scanState.target,
    engagementId: scanState.engagementId,
    status: scanState.status,
    phases: [...scanState.phases],
    totalFindings: scanState.totalFindings,
    currentPhase: scanState.currentPhase,
    log: [...scanState.log],
    startTime: scanState.startTime,
    durationMs: scanState.durationMs,
    analysisCurrent: scanState.analysisCurrent,
    analysisTotal: scanState.analysisTotal,
    errorHints: [...scanState.errorHints],
  }
}

function persistActive() {
  if (activeEngagementId) savedStates.set(activeEngagementId, snapshot())
}

function restore(id: string) {
  const saved = savedStates.get(id)
  if (saved) {
    setScanState(saved)
  } else {
    setScanState({ ...initialState, target: scanState.target, engagementId: id })
  }
  activeEngagementId = id
}

export function getScanState() {
  return scanState
}

export function setActiveEngagement(engagementId: string) {
  persistActive()
  restore(engagementId)
}

export function initScan(target: string, engagementId: string) {
  persistActive()
  savedStates.delete(engagementId)
  setScanState({
    ...initialState,
    target,
    engagementId,
    status: "running",
    startTime: Date.now(),
  })
  activeEngagementId = engagementId
}

export function addPhase(phase: { id: string; name: string; index: number; total: number }) {
  persistActive()
  setScanState("phases", (prev) => [
    ...prev,
    { ...phase, status: "running" as const, findings: 0, errors: [] },
  ])
  setScanState("currentPhase", phase.index)
}

export function completePhase(index: number, findings: number, errors: string[], status?: "completed" | "partial" | "failed") {
  if (scanState.phases[index]?.status === "completed" || scanState.phases[index]?.status === "partial" || scanState.phases[index]?.status === "failed") return
  persistActive()
  const resolvedStatus = status ?? (errors.length > 0 && findings > 0 ? "partial" : errors.length > 0 ? "failed" : "completed")
  setScanState("phases", index, "status", resolvedStatus)
  setScanState("phases", index, "findings", findings)
  setScanState("phases", index, "errors", errors)
  setScanState("totalFindings", (prev) => prev + findings)
}

export function appendLog(msg: string) {
  persistActive()
  setScanState("log", (prev) => [...prev, msg])
}

export function completeScan(success: boolean) {
  persistActive()
  setScanState("status", success ? "completed" : "failed")
  setScanState("durationMs", Date.now() - scanState.startTime)
}

export function setTotalFindings(count: number) {
  persistActive()
  setScanState("totalFindings", count)
}

export function addErrorHint(hint: ErrorHintData) {
  persistActive()
  setScanState("errorHints", (prev) => [...prev, hint])
}

export function clearErrorHints() {
  persistActive()
  setScanState("errorHints", [])
}

export function resetScan() {
  persistActive()
  setScanState({ ...initialState })
  activeEngagementId = null
}

function findPhaseIndex(phaseId: string): number {
  return scanState.phases.findIndex((p) => p.id === phaseId)
}

function drainQueue() {
  while (_pendingQueue.length > 0) {
    const next = _pendingQueue.shift()!
    const prevActive = activeEngagementId
    if (next.engagementId && next.engagementId !== activeEngagementId) {
      persistActive()
      restore(next.engagementId)
    }
    processEventInner(next.event, next.engagementId)
    if (next.engagementId && next.engagementId !== prevActive) {
      persistActive()
      if (prevActive) restore(prevActive)
    }
  }
  _processingLock = null
}

function processEventInner(event: ProgressEvent, engagementId?: string) {
  switch (event.type) {
    case "phase_start":
      addPhase({ id: event.phaseId, name: event.name, index: scanState.phases.length, total: event.total })
      break
    case "phase_complete": {
      const ci = findPhaseIndex(event.phaseId)
      const ps = "status" in event ? event.status : undefined
      if (ci >= 0) completePhase(ci, event.findings, [], ps === "PARTIAL" ? "partial" : ps === "COMPLETED" ? "completed" : undefined)
      break
    }
    case "phase_error": {
      const ei = findPhaseIndex(event.phaseId)
      if (ei >= 0) completePhase(ei, 0, [event.error], "failed")
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
    case "phase_replan":
      appendLog(`Replan: ${event.count} new phase(s) inserted`)
      break
    case "error_hint":
      addErrorHint({
        tool: event.tool,
        summary: event.summary,
        detail: event.detail,
        remediation: event.remediation,
        hintCommand: event.hintCommand,
        docsUrl: event.docsUrl,
        errorId: event.errorId,
      })
      appendLog(`[!] ${event.summary}`)
      break
    default:
      break
  }
}

export function handleProgressEvent(event: ProgressEvent, engagementId?: string) {
  const targetId = engagementId ?? activeEngagementId ?? ""

  if (_processingLock && _processingLock !== targetId) {
    _pendingQueue.push({ event, engagementId })
    return
  }

  const isNewLock = !_processingLock
  if (isNewLock) _processingLock = targetId

  const prevActive = activeEngagementId
  if (engagementId && engagementId !== activeEngagementId) {
    persistActive()
    restore(engagementId)
  }

  processEventInner(event, engagementId)

  if (engagementId && engagementId !== prevActive) {
    persistActive()
    if (prevActive) restore(prevActive)
  }

  if (isNewLock) drainQueue()
}
