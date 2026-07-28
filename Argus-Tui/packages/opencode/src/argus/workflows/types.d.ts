import { Capability } from "../shared/capabilities";
export type { WorkflowDefinition, PhaseDefinition } from "../planner/types";
export interface ToolRequirement {
    name: string;
    capabilities: Capability[];
    requires_auth: boolean;
    destructive: boolean;
    timeout_seconds: number;
    scoring?: {
        confidence_score: number;
        coverage_score: number;
    };
}
export interface ApprovalGate {
    name: string;
    label: string;
    require_confirmation: boolean;
    destructive: boolean;
    auth_testing: boolean;
    privilege_escalation: boolean;
}
