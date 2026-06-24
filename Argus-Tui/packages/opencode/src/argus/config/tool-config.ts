import { StoragePaths } from "../storage/paths"

export interface ToolSettings {
  enabled?: string[]
  disabled?: string[]
  paths?: Record<string, string>
  timeouts?: Record<string, number>
  circuit_breaker?: {
    max_failures?: number
    cooldown_ms?: number
  }
}

export interface ResolvedToolConfig {
  isEnabled(toolName: string): boolean
  getPath(toolName: string): string | undefined
  getTimeout(toolName: string): number | undefined
  getCircuitBreakerConfig(): { maxFailures: number; cooldownMs: number }
}

const DEFAULT_CIRCUIT_BREAKER = {
  maxFailures: 5,
  cooldownMs: 300_000,
}

export class ToolConfig implements ResolvedToolConfig {
  private settings: ToolSettings

  constructor(settings?: ToolSettings) {
    this.settings = settings ?? {}
  }

  static async load(): Promise<ToolConfig> {
    try {
      const { readFileSync } = await import("fs")
      const { join } = await import("path")
      const { parse } = await import("yaml")

      const paths = [
        join(process.cwd(), "argus.config.yaml"),
        StoragePaths.config,
      ]

      for (const configPath of paths) {
        try {
          const raw = readFileSync(configPath, "utf-8")
          const parsed = parse(raw)
          if (parsed?.tools) {
            return new ToolConfig(parsed.tools)
          }
        } catch { /* file not found or invalid */ }
      }
    } catch { /* imports failed */ }

    return new ToolConfig({})
  }

  isEnabled(toolName: string): boolean {
    if (this.settings.disabled?.includes(toolName)) return false
    if (this.settings.enabled && this.settings.enabled.length > 0 && !this.settings.enabled.includes(toolName)) return false
    return true
  }

  getPath(toolName: string): string | undefined {
    return this.settings.paths?.[toolName]
  }

  getTimeout(toolName: string): number | undefined {
    return this.settings.timeouts?.[toolName]
  }

  getCircuitBreakerConfig(): { maxFailures: number; cooldownMs: number } {
    return {
      maxFailures: this.settings.circuit_breaker?.max_failures ?? DEFAULT_CIRCUIT_BREAKER.maxFailures,
      cooldownMs: this.settings.circuit_breaker?.cooldown_ms ?? DEFAULT_CIRCUIT_BREAKER.cooldownMs,
    }
  }
}
