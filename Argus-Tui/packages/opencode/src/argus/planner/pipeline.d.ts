export interface DataContract {
    consumes: string[];
    provides: string[];
}
export interface PipelineStep {
    tool: string;
    capabilities: string[];
    contracts: DataContract;
    satisfied: boolean;
}
export interface PipelineResult {
    steps: PipelineStep[];
    gaps: string[];
    circular: boolean;
}
export declare function resolvePipeline(tools: Array<{
    name: string;
    capabilities: string[];
    consumes?: string[];
    provides?: string[];
}>, initialData?: string[]): PipelineResult;
export declare function formatPipelineGaps(gaps: string[], availableTools: string[]): string;
