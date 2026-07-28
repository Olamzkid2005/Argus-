import type { PlannerContext, AssessmentPlan, PhaseExecutionRequest } from "./types";
import { WorkflowRegistry } from "../workflows/registry";
import { ToolRegistry } from "../workflows/tool-registry";
import type { ProgressEvent } from "../shared/progress";
export declare const MAX_REPLANS: number;
export declare const LLM_MAX_REPLANS: number;
interface PlanOptions {
    useLLM?: boolean;
    /** Optional progress callback for emitting structured events to the TUI */
    onProgress?: (event: ProgressEvent) => void;
}
export declare class WorkflowPlanner {
    private workflowRegistry;
    private toolRegistry;
    constructor(workflowRegistry: WorkflowRegistry, toolRegistry: ToolRegistry);
    plan(target: string, context?: Partial<PlannerContext>, options?: PlanOptions): Promise<AssessmentPlan>;
    replan(context: PlannerContext): Promise<PhaseExecutionRequest[] | null>;
}
export {};
