import type { PhaseExecutionRequest } from "../planner/types";
import type { ApprovalGate } from "./types";
export interface ApprovalResult {
    approved: boolean;
    reason?: string;
}
export declare class ApprovalService {
    private gates;
    constructor();
    private registerDefaultGates;
    registerGate(gate: ApprovalGate): void;
    getGate(name: string): ApprovalGate | undefined;
    getRequiredGates(workflowApprovalRequired: Record<string, boolean> | undefined): ApprovalGate[];
    needsApproval(phase: PhaseExecutionRequest, requiredGates: ApprovalGate[]): ApprovalGate | null;
    requestApproval(gate: ApprovalGate, phaseName: string, target: string): Promise<ApprovalResult>;
    /**
     * Per-tool destructive confirmation (Task 4.1).
     *
     * Prompt the user before running a tool that is marked `destructive: true`
     * in the tool definitions. This runs AFTER phase-level approval, giving
     * users a second safety prompt before individual destructive tools execute.
     *
     * Respects the same auto-approve and non-TTY policies as phase-level gates:
     *   - ARGUS_AUTO_APPROVE=1 → auto-approved with audit timestamp
     *   - Non-TTY → auto-approved (phase was already approved at this point)
     *   - TTY → interactive prompt
     *
     * @returns { approved: false, reason: "..." } when the user declines or
     *          the tool times out, allowing the caller to skip just this tool
     *          without aborting the entire phase.
     */
    confirmDestructiveTool(toolName: string, toolLabel: string, target: string): Promise<ApprovalResult>;
    /**
     * Shared interactive prompt logic.
     * Reads a single line from stdin with a 30-second timeout.
     */
    private promptConfirmation;
}
