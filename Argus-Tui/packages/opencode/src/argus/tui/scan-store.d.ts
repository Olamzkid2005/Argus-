/**
 * ScanStore — Engagement-scoped reactive state for assessments.
 *
 * Maintains separate ScanState per engagementId so concurrent assessments
 * don't contaminate each other's progress. The TUI reads from the
 * currently active engagement's state via getScanState().
 */
import type { ErrorHintData, ProgressEvent } from "../shared/progress";
export interface ScanPhase {
    id: string;
    name: string;
    index: number;
    total: number;
    status: "pending" | "running" | "completed" | "partial" | "failed";
    findings: number;
    errors: string[];
}
export interface LLMAnalysisSuggestion {
    capabilities: string[];
    reasoning: string;
}
export interface LLMReplanEntry {
    phaseName: string;
    reasoning: string;
    suggestedCapabilities: string[];
    stopAssessment: boolean;
    llmModel: string;
}
export interface ScanState {
    target: string;
    engagementId: string;
    status: "idle" | "running" | "completed" | "failed";
    phases: ScanPhase[];
    totalFindings: number;
    currentPhase: number;
    log: string[];
    startTime: number;
    durationMs: number;
    analysisCurrent: number;
    analysisTotal: number;
    errorHints: ErrorHintData[];
    verificationStatus: "idle" | "running" | "completed";
    verificationCurrent: number;
    verificationTotal: number;
    verificationPassed: number;
    verificationFailed: number;
    llmPlanningStatus: "idle" | "running" | "completed" | "failed";
    llmPlanningTargetAnalysis: string;
    llmPlanningSuggestions: LLMAnalysisSuggestion[];
    llmPlanningError: string;
    /** Model identifier used by the planner (e.g. "openai/gpt-4o-mini") */
    llmPlanningModel: string;
    /** Full env var config description for model tooltip display */
    llmPlanningModelConfig: string;
    llmReplanEntries: LLMReplanEntry[];
    llmReplanStatus: "idle" | "running" | "completed";
    attackGraphSnapshot: any | null;
}
export declare function getScanState(): ScanState;
export declare function setActiveEngagement(engagementId: string): void;
export declare function initScan(target: string, engagementId: string): void;
export declare function addPhase(phase: {
    id: string;
    name: string;
    index: number;
    total: number;
}): void;
export declare function completePhase(phaseId: string, findings: number, errors: string[], status?: "completed" | "partial" | "failed"): void;
export declare function appendLog(msg: string): void;
export declare function completeScan(success: boolean): void;
export declare function setTotalFindings(count: number): void;
export declare function addErrorHint(hint: ErrorHintData): void;
export declare function clearErrorHints(): void;
/**
 * Update the planner model displayed in the scan dashboard.
 * Called after LLMPlannerService.switchModel() to keep the
 * scan-store in sync with the newly selected model.
 */
export declare function setPlannerModel(modelId: string, modelConfig: string): void;
export declare function resetScan(): void;
export declare function handleProgressEvent(event: ProgressEvent, engagementId?: string): Promise<void>;
