/**
 * Custom OpenAI-compatible cyber models — TUI half of the unified registry.
 *
 * One entry in `argus-workers/config/custom_models.json` feeds both runtimes.
 * The Python workers resolve `LLM_MODEL=<name>` directly
 * (`config/custom_models.py`); OpenCode itself cannot read that file, so this
 * module generates the `opencode.json` provider block the operator pastes once
 * to make the same endpoint selectable as `ARGUS_PLANNER_MODEL`.
 *
 * Nothing here touches provider selection policy (`./model-selection`): once
 * the provider exists in the operator's OpenCode config it is an ordinary
 * configured provider.
 */

import { readFileSync } from "node:fs"
import { join } from "node:path"
import { PROJECT_ROOT } from "../shared/path"

export const CUSTOM_MODELS_PATH = join(
  PROJECT_ROOT,
  "argus-workers",
  "config",
  "custom_models.json",
)

export interface CustomModelEntry {
  readonly name: string
  readonly baseURL: string
  readonly model: string
  /** Env var holding the credential, or null for a keyless local endpoint. */
  readonly apiKeyEnv: string | null
  readonly description: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

/** Parse and validate registry text. Throws on any malformed entry. */
export function parseCustomModelsRegistry(text: string): CustomModelEntry[] {
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch (error) {
    throw new Error(`Custom model registry is not valid JSON: ${(error as Error).message}`)
  }
  if (!isRecord(raw)) throw new Error("Custom model registry must be a JSON object.")
  const models = raw["models"] ?? {}
  if (!isRecord(models)) throw new Error('Custom model registry "models" must be an object.')
  const entries: CustomModelEntry[] = []
  for (const [name, value] of Object.entries(models)) {
    entries.push(validateCustomModelEntry(name, value))
  }
  return entries.sort((a, b) => a.name.localeCompare(b.name))
}

export function validateCustomModelEntry(name: string, value: unknown): CustomModelEntry {
  const where = `custom model '${name}'`
  if (!name || name.includes("/")) {
    throw new Error(`${where}: name must be a non-empty slash-free string.`)
  }
  if (!isRecord(value)) throw new Error(`${where}: entry must be an object.`)
  const baseURL = String(value["base_url"] ?? "").trim()
  if (!/^https?:\/\//.test(baseURL)) {
    throw new Error(`${where}: base_url must be an http(s) URL.`)
  }
  const model = String(value["model"] ?? "").trim()
  if (!model) throw new Error(`${where}: model must be a non-empty model id.`)
  const rawKey = value["api_key_env"]
  let apiKeyEnv: string | null = null
  if (rawKey !== undefined && rawKey !== null) {
    apiKeyEnv = String(rawKey).trim()
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(apiKeyEnv)) {
      throw new Error(`${where}: api_key_env must be a valid env var name or null.`)
    }
  }
  return {
    name,
    baseURL: baseURL.replace(/\/+$/, ""),
    model,
    apiKeyEnv,
    description: String(value["description"] ?? ""),
  }
}

/** Read the shipped registry file. Returns [] when it holds no models. */
export function listCustomModels(registryPath: string = CUSTOM_MODELS_PATH): CustomModelEntry[] {
  return parseCustomModelsRegistry(readFileSync(registryPath, "utf-8"))
}

/** Find one entry by name. Returns undefined when not registered. */
export function resolveCustomModel(
  name: string,
  registryPath: string = CUSTOM_MODELS_PATH,
): CustomModelEntry | undefined {
  return listCustomModels(registryPath).find((entry) => entry.name === name.trim())
}

/**
 * Render the `opencode.json` provider block for one entry.
 *
 * The provider id is `argus-<name>` so it can never collide with a provider
 * the operator configured themselves. After pasting, select it with
 * `ARGUS_PLANNER_MODEL=argus-<name>/<model>`.
 */
export function opencodeProviderSnippet(entry: CustomModelEntry): string {
  const providerID = `argus-${entry.name}`
  const apiKey = entry.apiKeyEnv ? `{env:${entry.apiKeyEnv}}` : "not-needed"
  return JSON.stringify(
    {
      $schema: "https://opencode.ai/config.json",
      provider: {
        [providerID]: {
          npm: "@ai-sdk/openai-compatible",
          name: `Argus ${entry.name}`,
          options: { baseURL: `${entry.baseURL}/chat/completions`, apiKey },
          models: { [entry.model]: { name: entry.description || entry.model } },
        },
      },
    },
    null,
    2,
  )
}
