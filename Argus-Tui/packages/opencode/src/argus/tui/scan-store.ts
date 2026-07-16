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

export interface LLMAnalysisSuggestion {
  capabilities: string[]
  reasoning: string
}

export interface LLMReplanEntry {
  phaseName: string
  reasoning: string
  suggestedCapabilities: string[]
  stopAssessment: boolean
  llmModel: string
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
  // Verification tracking state
  verificationStatus: "idle" | "running" | "completed"
  verificationCurrent: number
  verificationTotal: number
  verificationPassed: number
  verificationFailed: number
  // LLM planning analysis state
  llmPlanningStatus: "idle" | "running" | "completed" | "failed"
  llmPlanningTargetAnalysis: string
  llmPlanningSuggestions: LLMAnalysisSuggestion[]
  llmPlanningError: string
  /** Model identifier used by the planner (e.g. "openai/gpt-4o-mini") */
  llmPlanningModel: string
  /** Full env var config description for model tooltip display */
  llmPlanningModelConfig: string
  // LLM replan analysis history
  llmReplanEntries: LLMReplanEntry[]
  llmReplanStatus: "idle" | "running" | "completed"
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
  verificationStatus: "idle",
  verificationCurrent: 0,
  verificationTotal: 0,
  verificationPassed: 0,
  verificationFailed: 0,
  llmPlanningStatus: "idle",
  llmPlanningTargetAnalysis: "",
  llmPlanningSuggestions: [] as LLMAnalysisSuggestion[],
  llmPlanningError: "",
  llmPlanningModel: "",
  llmPlanningModelConfig: "",
  llmReplanEntries: [] as LLMReplanEntry[],
  llmReplanStatus: "idle",
}

const [scanState, setScanState] = createStore<ScanState>({ ...initialState })

const savedStates = new Map<string, ScanState>()

let activeEngagementId: string | null = null
const _eventQueues = new Map<string, Promise<void>>()

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
    verificationStatus: scanState.verificationStatus,
    verificationCurrent: scanState.verificationCurrent,
    verificationTotal: scanState.verificationTotal,
    verificationPassed: scanState.verificationPassed,
    verificationFailed: scanState.verificationFailed,
    llmPlanningStatus: scanState.llmPlanningStatus,
    llmPlanningTargetAnalysis: scanState.llmPlanningTargetAnalysis,
    llmPlanningSuggestions: [...scanState.llmPlanningSuggestions],
    llmPlanningError: scanState.llmPlanningError,
    llmPlanningModel: scanState.llmPlanningModel,
    llmPlanningModelConfig: scanState.llmPlanningModelConfig,
    llmReplanEntries: [...scanState.llmReplanEntries],
    llmReplanStatus: scanState.llmReplanStatus,
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
  // Don't add a phase that already exists — replan phases share names with
  // existing phases and must not create duplicates in the scan state.
  const idx = scanState.phases.findIndex((p) => p.id === phase.id)
  if (idx >= 0) return
  persistActive()
  setScanState("phases", (prev) => [
    ...prev,
    { ...phase, status: "running" as const, findings: 0, errors: [] },
  ])
  setScanState("currentPhase", phase.index)
}

export function completePhase(phaseId: string, findings: number, errors: string[], status?: "completed" | "partial" | "failed") {
  const idx = scanState.phases.findIndex((p) => p.id === phaseId)
  if (idx < 0) return
  if (scanState.phases[idx]?.status === "completed" || scanState.phases[idx]?.status === "partial" || scanState.phases[idx]?.status === "failed") return
  persistActive()
  const resolvedStatus = status ?? (errors.length > 0 && findings > 0 ? "partial" : errors.length > 0 ? "failed" : "completed")
  setScanState("phases", idx, "status", resolvedStatus)
  setScanState("phases", idx, "findings", findings)
  setScanState("phases", idx, "errors", errors)
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

/**
 * Update the planner model displayed in the scan dashboard.
 * Called after LLMPlannerService.switchModel() to keep the
 * scan-store in sync with the newly selected model.
 */
export function setPlannerModel(modelId: string, modelConfig: string) {
  persistActive()
  setScanState("llmPlanningModel", modelId)
  setScanState("llmPlanningModelConfig", modelConfig)
}

export function resetScan() {
  persistActive()
  setScanState({ ...initialState })
  activeEngagementId = null
}

function processEventInner(event: ProgressEvent, engagementId?: string) {
  switch (event.type) {
    case "phase_start":
      addPhase({ id: event.phaseId, name: event.name, index: scanState.phases.length, total: event.total })
      break
    case "phase_complete": {
      const ps = "status" in event ? event.status : undefined
      completePhase(event.phaseId, event.findings, [], ps === "PARTIAL" ? "partial" : ps === "COMPLETED" ? "completed" : undefined)
      break
    }
    case "phase_error": {
      completePhase(event.phaseId, 0, [event.error], "failed")
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
    case "verification_start":
      setScanState("verificationStatus", "running")
      setScanState("verificationCurrent", 0)
      setScanState("verificationTotal", event.total)
      setScanState("verificationPassed", 0)
      setScanState("verificationFailed", 0)
      appendLog(`Verification starting: ${event.total} finding(s)`)
      break
    case "verification_progress": {
      setScanState("verificationCurrent", event.current)
      setScanState("verificationTotal", event.total)
      if (event.findingTitle) {
        appendLog(`Verifying: ${event.findingSubtype ?? "finding"} — ${event.findingTitle}`)
      }
      break
    }
    case "verification_complete":
      setScanState("verificationStatus", "completed")
      setScanState("verificationPassed", event.passed)
      setScanState("verificationFailed", event.failed)
      appendLog(`Verification complete: ${event.passed} passed, ${event.failed} failed`)
      break
    case "llm_planning_start":
      setScanState("llmPlanningStatus", "running")
      setScanState("llmPlanningTargetAnalysis", "")
      setScanState("llmPlanningSuggestions", [])
      setScanState("llmPlanningError", "")
      appendLog(`LLM analysis started: ${event.phase} planning`)
      break
    case "llm_planning_complete":
      setScanState("llmPlanningStatus", "completed")
      setScanState("llmPlanningTargetAnalysis", event.targetAnalysis)
      setScanState("llmPlanningSuggestions", event.suggestions.map((s) => ({ capabilities: s.capabilities, reasoning: s.reasoning })))
      setScanState("llmPlanningModel", event.llmModel)
      setScanState("llmPlanningModelConfig", event.modelEnvDescription)
      appendLog(`LLM analysis complete: ${event.suggestions.length} phase suggestion(s) for ${event.phase} planning`)
      break
    case "llm_planning_error":
      setScanState("llmPlanningStatus", "failed")
      setScanState("llmPlanningError", event.error)
      appendLog(`LLM analysis failed: ${event.error}`)
      break
    case "llm_replan_analysis":
      setScanState("llmReplanStatus", "completed")
      setScanState("llmReplanEntries", (prev) => [
        ...prev,
        {
          phaseName: event.label,
          reasoning: event.reasoning,
          suggestedCapabilities: event.suggestedCapabilities,
          stopAssessment: event.stopAssessment,
          llmModel: event.llmModel,
        },
      ])
      if (event.stopAssessment) {
        appendLog(`LLM suggests stopping assessment: ${event.reasoning}`)
      } else if (event.suggestedCapabilities.length > 0) {
        appendLog(`LLM suggests next capabilities: ${event.suggestedCapabilities.join(", ")}`)
      }
      break
    default:
      break
  }
}

export async function handleProgressEvent(event: ProgressEvent, engagementId?: string) {
  const targetId = engagementId ?? activeEngagementId ?? ""

  // Chain events per engagement so they process in order without races
  const prev = _eventQueues.get(targetId) ?? Promise.resolve()
  const next = prev.then(async () => {
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
  }).catch(() => {})
  _eventQueues.set(targetId, next)
  // Await the chain so callers can await handleProgressEvent and be sure
  // the event has been processed before continuing.
  await next
}
