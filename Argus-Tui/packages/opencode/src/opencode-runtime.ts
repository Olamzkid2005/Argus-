/**
 * @opencode/runtime — Public API surface for Argus modules.
 *
 * This is the ONLY entry point Argus modules may import from in the OpenCode
 * fork. Direct imports into OpenCode implementation files are prohibited by
 * the no-restricted-imports ESLint rule (see .eslintrc.json).
 *
 * Argus modules should import like this:
 *   import { IProviderManager, ISessionStore } from "@opencode/runtime"
 *
 * NOT like this:
 *   import { Provider } from "../../opencode/providers/provider"   // ❌
 *   import { SessionManager } from "../../opencode/sessions/manager" // ❌
 */

// ── Provider Interfaces ──
export interface IProviderManager {
  resolve(model: string): { provider: string; modelName: string }
  getApiKey(provider: string): string | undefined
  listModels(): string[]
}

// ── Session Interfaces ──
export interface ISessionStore {
  create(target: string): { id: string; target: string; phase: string }
  get(id: string): { id: string; target: string; phase: string } | null
  update(id: string, updates: Partial<{ target: string; phase: string }>): void
  list(limit?: number): Array<{ id: string; target: string; phase: string; created_at: string }>
}

// ── Runtime Events Interface ──
export interface IRuntimeEvents {
  on(event: string, handler: (...args: unknown[]) => void): void
  off(event: string, handler: (...args: unknown[]) => void): void
  emit(event: string, ...args: unknown[]): boolean
}

// ── Command Registry Interface ──
export interface ICommandRegistry {
  register(name: string, handler: (args: Record<string, unknown>) => Promise<void>): void
  execute(name: string, args: Record<string, unknown>): Promise<void>
  list(): string[]
}

// ── Config Interface ──
export interface IConfigManager {
  get(key: string): unknown
  set(key: string, value: unknown): void
  load(): void
  save(): void
}

// ── Feature Flag Interface ──
export interface IFeatureFlags {
  isEnabled(feature: string): boolean
  allEnabled(...features: string[]): boolean
  anyEnabled(...features: string[]): boolean
}
