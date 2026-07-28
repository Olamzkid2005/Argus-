import type { WorkflowDefinition } from "./types";
export declare function loadWorkflowYaml(path: string): WorkflowDefinition;
export declare function loadAllWorkflows(workflowsDir: string): WorkflowDefinition[];
