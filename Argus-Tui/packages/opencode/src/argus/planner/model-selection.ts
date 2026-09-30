/**
 * Planner model *policy* — pure, dependency-free.
 *
 * Argus must run on the providers the operator configured in OpenCode, never
 * on whatever provider credentials happen to be exported into the surrounding
 * shell. This module holds that policy so it can be unit-tested without
 * booting the OpenCode Effect runtime (see ./model-registry for the I/O side).
 */

/**
 * Ambient environment variables that identify a provider.
 * These belong to whichever tool exported them — never to Argus.
 */
export const AMBIENT_LLM_ENV_VARS = [
  "OPENAI_API_KEY",
  "OPENAI_BASE_URL",
  "OPENAI_MODEL",
  "ANTHROPIC_API_KEY",
  "OPENCODE_API_KEY",
] as const

/** Opt back in to ambient provider env vars. Deliberately explicit. */
export const ALLOW_AMBIENT_ENV_VAR = "ARGUS_ALLOW_AMBIENT_LLM_ENV"

/** Selection knob: `provider/model` or a bare model id. */
export const PLANNER_MODEL_ENV_VAR = "ARGUS_PLANNER_MODEL"

/** OpenCode's own gateway providers (no separate credential required). */
export function isOpenCodeOwnedProvider(providerID: string): boolean {
  return providerID === "opencode" || providerID.startsWith("opencode-")
}

export function ambientEnvAllowed(env: NodeJS.ProcessEnv = process.env): boolean {
  const value = env[ALLOW_AMBIENT_ENV_VAR]
  return value === "1" || value === "true"
}

/**
 * Names of ambient LLM env vars that are set but will not be used.
 * Reported by `doctor` so this can never silently route Argus elsewhere.
 */
export function ignoredAmbientLlmEnvVars(env: NodeJS.ProcessEnv = process.env): string[] {
  if (ambientEnvAllowed(env)) return []
  return AMBIENT_LLM_ENV_VARS.filter((key) => (env[key] ?? "").trim() !== "")
}

export interface ModelRef {
  readonly providerID: string
  readonly modelID: string
}

export type ModelSelection =
  | { readonly ok: true; readonly ref: ModelRef; readonly source: "explicit" | "default" | "first-configured" }
  | { readonly ok: false; readonly reason: string }

/** Minimal shape needed from the registry to make a selection. */
export interface SelectableProvider {
  readonly models: Record<string, unknown>
}

/**
 * Whether a provider may run Argus's planner.
 * Only OpenCode-configured providers (auth.json) and OpenCode's own gateway.
 */
export function isSelectableProviderID(
  providerID: string,
  configured: ReadonlySet<string>,
  allowAmbient: boolean,
): boolean {
  if (allowAmbient) return true
  return configured.has(providerID) || isOpenCodeOwnedProvider(providerID)
}

/**
 * Pure selection policy.
 *
 * Precedence:
 *   1. `preferred` (`provider/model`, or a bare model id found on a configured
 *      provider) — resolved strictly, so a typo is an error rather than a
 *      silent fallback to a different provider.
 *   2. OpenCode's own default model, when its provider is selectable.
 *   3. First model of the first selectable provider (OpenCode-owned first).
 */
export function selectPlannerModelRef(input: {
  readonly preferred?: string | undefined
  readonly configured: Iterable<string>
  readonly available: Record<string, SelectableProvider>
  readonly defaultModel?: ModelRef | undefined
  readonly allowAmbient?: boolean
}): ModelSelection {
  const configured = new Set(input.configured)
  const allowAmbient = input.allowAmbient ?? false
  const selectable = Object.keys(input.available)
    .filter((id) => isSelectableProviderID(id, configured, allowAmbient))
    .sort((a, b) => {
      const aOwned = isOpenCodeOwnedProvider(a)
      const bOwned = isOpenCodeOwnedProvider(b)
      if (aOwned !== bOwned) return aOwned ? -1 : 1
      return a.localeCompare(b)
    })

  if (selectable.length === 0) {
    return {
      ok: false,
      reason:
        "No providers are configured in OpenCode. Run `opencode auth login` (or configure a provider " +
        "in the OpenCode TUI) to make a model available to Argus.",
    }
  }

  const hasModel = (providerID: string, modelID: string) =>
    Object.prototype.hasOwnProperty.call(input.available[providerID]?.models ?? {}, modelID)

  const preferred = input.preferred?.trim()
  if (preferred) {
    // `provider/model`
    if (preferred.includes("/")) {
      const slash = preferred.indexOf("/")
      const providerID = preferred.slice(0, slash)
      const modelID = preferred.slice(slash + 1)
      if (!selectable.includes(providerID)) {
        return {
          ok: false,
          reason:
            `ARGUS_PLANNER_MODEL=${preferred} names provider '${providerID}', which is not configured in ` +
            `OpenCode (selectable: ${selectable.join(", ")}).`,
        }
      }
      if (!hasModel(providerID, modelID)) {
        return {
          ok: false,
          reason: `ARGUS_PLANNER_MODEL=${preferred}: provider '${providerID}' has no model '${modelID}'.`,
        }
      }
      return { ok: true, ref: { providerID, modelID }, source: "explicit" }
    }

    // Bare model id: look for it across selectable providers.
    for (const providerID of selectable) {
      if (hasModel(providerID, preferred)) {
        return { ok: true, ref: { providerID, modelID: preferred }, source: "explicit" }
      }
    }
    return {
      ok: false,
      reason:
        `ARGUS_PLANNER_MODEL=${preferred} does not match any model on a configured provider ` +
        `(${selectable.join(", ")}).`,
    }
  }

  if (
    input.defaultModel &&
    selectable.includes(input.defaultModel.providerID) &&
    hasModel(input.defaultModel.providerID, input.defaultModel.modelID)
  ) {
    return { ok: true, ref: input.defaultModel, source: "default" }
  }

  const providerID = selectable[0]!
  const modelID = Object.keys(input.available[providerID]?.models ?? {}).sort()[0]
  if (!modelID) {
    return { ok: false, reason: `Provider '${providerID}' advertises no models.` }
  }
  return { ok: true, ref: { providerID, modelID }, source: "first-configured" }
}
