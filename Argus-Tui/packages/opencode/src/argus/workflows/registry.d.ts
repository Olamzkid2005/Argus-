import type { WorkflowDefinition } from "./types";
import { Capability } from "../shared/capabilities";
export declare class WorkflowRegistry {
    private workflows;
    private workflowsDir;
    constructor(workflowsDir?: string);
    loadAll(): WorkflowDefinition[];
    getWorkflow(name: string): WorkflowDefinition | undefined;
    listWorkflows(): WorkflowDefinition[];
    findByCapabilities(required: Capability[]): WorkflowDefinition | null;
    addWorkflow(path: string): void;
}
