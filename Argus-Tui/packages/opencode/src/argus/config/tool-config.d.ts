export interface ToolSettings {
    enabled?: string[];
    disabled?: string[];
    paths?: Record<string, string>;
    timeouts?: Record<string, number>;
    circuit_breaker?: {
        max_failures?: number;
        cooldown_ms?: number;
    };
}
export interface ResolvedToolConfig {
    isEnabled(toolName: string): boolean;
    getPath(toolName: string): string | undefined;
    getTimeout(toolName: string): number | undefined;
    getCircuitBreakerConfig(): {
        maxFailures: number;
        cooldownMs: number;
    };
}
export declare class ToolConfig implements ResolvedToolConfig {
    private settings;
    constructor(settings?: ToolSettings);
    static load(): Promise<ToolConfig>;
    isEnabled(toolName: string): boolean;
    getPath(toolName: string): string | undefined;
    getTimeout(toolName: string): number | undefined;
    getCircuitBreakerConfig(): {
        maxFailures: number;
        cooldownMs: number;
    };
}
