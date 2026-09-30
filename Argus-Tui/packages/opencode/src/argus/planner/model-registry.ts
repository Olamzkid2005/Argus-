/**
 * Planner model resolution — OpenCode provider registry only.
 *
 * Argus must run on the providers the operator configured *in OpenCode*
 * (auth.json + the models.dev catalog), exactly like OpenCode's own agent.
 * It must NOT silently adopt whatever provider credentials happen to be
 * exported into the surrounding shell.
 *
 * Concretely, this module exists because of two production defects:
 *
 *   1. `llm-service.ts` used to resolve an API key from ambient
 *      `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENCODE_API_KEY` and then
 *      build a route with the `openai`/`anthropic` provider helpers. On a
 *      machine where some *other* tool had exported `OPENAI_API_KEY` +
 *      `OPENAI_BASE_URL`, Argus silently ran — and billed — that provider.
 *   2. Nothing in the Argus layer consulted the provider registry, so
 *      "Argus uses OpenCode's AI" was aspirational: `doctor` hand-rolled a
 *      partial auth.json reader purely for display.
 *
 * The selection *policy* lives in ./model-selection (pure, unit-tested);
 * this module performs the I/O against OpenCode's services.
 *
 * The route is built with `LLMNative.model()` — the same adapter the
 * OpenCode session layer uses to lower a registry model into an
 * `@opencode-ai/llm` route — so there is exactly one mapping from
 * registry entry to protocol/endpoint/auth in the codebase.
 */

import { Effect } from "effect"
import type { Model } from "@opencode-ai/llm"
import { InstanceStore } from "@/project/instance-store"
import { InstanceRef } from "@/effect/instance-ref"
import { Provider } from "@/provider/provider"
import { ProviderV2 } from "@opencode-ai/core/provider"
import { Auth } from "@/auth"
import { LLMNative } from "@/session/llm/native-request"
import {
  PLANNER_MODEL_ENV_VAR,
  ambientEnvAllowed,
  ignoredAmbientLlmEnvVars,
  isSelectableProviderID,
  selectPlannerModelRef,
  type ModelRef,
} from "./model-selection"

export {
  ALLOW_AMBIENT_ENV_VAR,
  AMBIENT_LLM_ENV_VARS,
  PLANNER_MODEL_ENV_VAR,
  ambientEnvAllowed,
  ignoredAmbientLlmEnvVars,
  isOpenCodeOwnedProvider,
  isSelectableProviderID,
  selectPlannerModelRef,
} from "./model-selection"
export type { ModelRef, ModelSelection, SelectableProvider } from "./model-selection"

/**
 * The OpenCode managed runtime is imported lazily: importing it constructs it,
 * which is only worth paying when the registry is actually consulted.
 * `booted` tracks whether this process started it, so the CLI entry can
 * release it on exit (otherwise the process never terminates).
 */
let booted = false

async function appRuntime() {
  const mod = await import("@/effect/app-runtime")
  booted = true
  return mod.AppRuntime
}

/**
 * Dispose the OpenCode managed runtime if the planner booted it.
 *
 * Call this from process-owning entry points (the Argus CLI). Hosts that embed
 * Argus (the OpenCode TUI/server) own the runtime themselves and must NOT call
 * this.
 */
export async function disposePlannerRuntime(): Promise<void> {
  if (!booted) return
  booted = false
  const mod = await import("@/effect/app-runtime")
  await mod.AppRuntime.dispose()
}

/**
 * The model configuration handed to the Python worker at `agent_init`.
 *
 * Argus has two runtimes that both need an LLM: this planner and the Python
 * engine that selects tools. Resolving the model twice would let them disagree
 * (one run planning on OpenCode's provider and selecting tools on something
 * else), so the planner resolves once and passes the concrete endpoint down.
 * The worker has no provider registry of its own — OpenCode's lives in this
 * process.
 */
export interface WorkerLlmConfig {
  /** Protocol the worker may speak. Only OpenAI-compatible chat today. */
  readonly provider: "openai-compatible"
  readonly providerID: string
  readonly model: string
  readonly apiKey: string
  /** Base URL; the worker appends `/chat/completions`. */
  readonly baseUrl: string
}

export type PlannerModelResolution =
  | {
      readonly ok: true
      readonly providerID: string
      readonly modelID: string
      readonly model: Model
      readonly source: "explicit" | "default" | "first-configured"
      readonly ignoredAmbientEnv: string[]
      /** Present when the worker can be pointed at the same model. */
      readonly handoff?: WorkerLlmConfig
      /** Why the worker cannot use this model, when that is the case. */
      readonly handoffUnsupportedReason?: string
    }
  | { readonly ok: false; readonly reason: string; readonly ignoredAmbientEnv: string[] }

/**
 * Map a registry model onto a worker-consumable endpoint.
 *
 * Only OpenAI-compatible chat is supported: the worker's LLM client speaks
 * OpenAI chat-completions (or Anthropic's wire format when explicitly
 * configured), so a provider on any other protocol cannot be handed over.
 */
function buildWorkerLlmConfig(model: Provider.Model, apiKey: string | undefined): WorkerLlmConfig | undefined {
  const npm = model.api.npm
  const url = model.api.url
  if (!apiKey || !url) return undefined
  if (npm !== "@ai-sdk/openai" && npm !== "@ai-sdk/openai-compatible") return undefined
  return {
    provider: "openai-compatible",
    providerID: String(model.providerID),
    model: model.api.id,
    apiKey,
    baseUrl: url,
  }
}

/** Snapshot of the registry needed by both the resolver and the TUI list. */
interface RegistrySnapshot {
  readonly configured: string[]
  readonly available: Record<string, { models: Record<string, unknown> }>
  readonly defaultModel: ModelRef | undefined
}

/**
 * Run `fn` against the OpenCode provider registry.
 *
 * `Provider`/`Auth` resolve through `InstanceState`, so an `InstanceRef` must
 * be provided — this mirrors how `effectCmd` loads an instance for one
 * command run, and disposes it afterwards.
 *
 * `any` in the requirements position: the services yielded inside `fn`
 * (Provider, Auth) are supplied by AppRuntime's managed layer at run time.
 */
async function withRegistry<T>(fn: (snapshot: RegistrySnapshot) => Effect.Effect<T, never, any>): Promise<T> {
  const runtime = await appRuntime()
  const { store, ctx } = await runtime.runPromise(
    InstanceStore.Service.use((store) =>
      store.load({ directory: process.cwd() }).pipe(Effect.map((ctx) => ({ store, ctx }))),
    ),
  )
  try {
    return await runtime.runPromise(
      Effect.gen(function* () {
        const auth = yield* Auth.Service
        const configured = Object.keys(yield* auth.all())
        const provider = yield* Provider.Service
        const available = yield* provider.list()
        const def = yield* provider.defaultModel()
        return yield* fn({
          configured,
          available: available as RegistrySnapshot["available"],
          defaultModel: def ? { providerID: String(def.providerID), modelID: String(def.modelID) } : undefined,
        })
      }).pipe(Effect.provideService(InstanceRef, ctx), Effect.orDie),
    )
  } finally {
    await runtime.runPromise(store.dispose(ctx))
  }
}

/** Build the `@opencode-ai/llm` route for one registry entry. */
function routeFor(snapshot: RegistrySnapshot, ref: ModelRef) {
  return Effect.gen(function* () {
    const provider = yield* Provider.Service
    // Model loading is a user-configuration outcome, not a defect.
    const modelOption = yield* provider
      .getModel(ProviderV2.ID.make(ref.providerID), ProviderV2.ModelID.make(ref.modelID))
      .pipe(Effect.option)
    if (modelOption._tag === "None") return undefined

    const info = snapshot.available[ref.providerID] as
      | { key?: string; options?: { apiKey?: unknown } }
      | undefined
    const apiKey =
      typeof info?.options?.apiKey === "string"
        ? info.options.apiKey
        : typeof info?.key === "string"
          ? info.key
          : undefined

    // `messages` is required by the shared adapter's input type but is not
    // read by `model()`; the session layer passes real messages here.
    return {
      route: LLMNative.model({ model: modelOption.value, apiKey, messages: [] }),
      model: modelOption.value,
      apiKey,
    }
  })
}

/**
 * Resolve the Argus planner model from OpenCode's provider registry.
 * Never reads ambient provider credentials.
 */
/**
 * Resolutions are cached for the process: the registry does not change
 * mid-run, and both the planner and the worker handoff must see the same
 * answer. `switchModel()` invalidates it.
 */
const resolutionCache = new Map<string, Promise<PlannerModelResolution>>()

export function invalidatePlannerModelCache(): void {
  resolutionCache.clear()
}

export function resolvePlannerModel(
  preferred: string | undefined = process.env[PLANNER_MODEL_ENV_VAR],
): Promise<PlannerModelResolution> {
  const cacheKey = preferred ?? ""
  const cached = resolutionCache.get(cacheKey)
  if (cached) return cached

  const pending = resolvePlannerModelUncached(preferred)
  resolutionCache.set(cacheKey, pending)
  return pending
}

/**
 * The configuration to hand the Python worker so it runs on the same model as
 * the planner. Resolves on first use and serves from the same cache.
 */
export async function resolveWorkerLlmConfig(): Promise<
  { readonly config: WorkerLlmConfig } | { readonly reason: string }
> {
  const resolution = await resolvePlannerModel()
  if (!resolution.ok) return { reason: resolution.reason }
  if (!resolution.handoff) {
    return { reason: resolution.handoffUnsupportedReason ?? "No worker-compatible endpoint for the resolved model." }
  }
  return { config: resolution.handoff }
}

async function resolvePlannerModelUncached(
  preferred: string | undefined,
): Promise<PlannerModelResolution> {
  const ignoredAmbientEnv = ignoredAmbientLlmEnvVars()
  const allowAmbient = ambientEnvAllowed()

  try {
    return await withRegistry<PlannerModelResolution>((snapshot) =>
      Effect.gen(function* () {
        const selection = selectPlannerModelRef({
          preferred,
          configured: snapshot.configured,
          available: snapshot.available,
          defaultModel: snapshot.defaultModel,
          allowAmbient,
        })
        if (!selection.ok) {
          return { ok: false as const, reason: selection.reason, ignoredAmbientEnv }
        }

        const resolved = yield* routeFor(snapshot, selection.ref)
        if (!resolved) {
          return {
            ok: false as const,
            reason:
              `Provider '${selection.ref.providerID}' could not load model ` +
              `'${selection.ref.modelID}' from the OpenCode registry.`,
            ignoredAmbientEnv,
          }
        }

        const { route, model, apiKey } = resolved
        const handoff = buildWorkerLlmConfig(model, apiKey)

        return {
          ok: true as const,
          providerID: selection.ref.providerID,
          modelID: selection.ref.modelID,
          model: route,
          source: selection.source,
          ignoredAmbientEnv,
          ...(handoff ? { handoff } : {}),
          ...(handoff
            ? {}
            : {
                handoffUnsupportedReason:
                  `Provider '${selection.ref.providerID}' (${model.api.npm}) is not OpenAI-compatible, ` +
                  `so the Python worker cannot be pointed at the same model.`,
              }),
        }
      }),
    )
  } catch (error: unknown) {
    return {
      ok: false,
      reason: `Could not read the OpenCode provider registry: ${error instanceof Error ? error.message : String(error)}`,
      ignoredAmbientEnv,
    }
  }
}

/**
 * List `provider/model` strings the operator can choose from — i.e. models on
 * providers configured in OpenCode. Used by the TUI model picker.
 */
export async function listPlannerModels(): Promise<string[]> {
  const allowAmbient = ambientEnvAllowed()
  try {
    return await withRegistry((snapshot) =>
      Effect.sync(() => {
        const configured = new Set(snapshot.configured)
        return Object.keys(snapshot.available)
          .filter((id) => isSelectableProviderID(id, configured, allowAmbient))
          .sort((a, b) => {
            const aOwned = a === "opencode" || a.startsWith("opencode-")
            const bOwned = b === "opencode" || b.startsWith("opencode-")
            if (aOwned !== bOwned) return aOwned ? -1 : 1
            return a.localeCompare(b)
          })
          .flatMap((providerID) =>
            Object.keys(snapshot.available[providerID]?.models ?? {})
              .sort()
              .map((modelID) => `${providerID}/${modelID}`),
          )
      }),
    )
  } catch {
    return []
  }
}
