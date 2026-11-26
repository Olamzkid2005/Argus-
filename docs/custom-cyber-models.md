# Custom OpenAI-compatible cyber models

One registration feeds both runtimes. Add an entry to
`argus-workers/config/custom_models.json` under `"models"`:

```json
"lab-vllm-cyber": {
  "base_url": "https://llm.lab.internal/v1",
  "model": "cyber-llama-8b",
  "api_key_env": "CYBER_MODEL_API_KEY",
  "description": "team-hosted security-tuned model"
}
```

- `base_url`: http(s) URL of the OpenAI-compatible endpoint (no `/chat/completions` suffix needed).
- `model`: the model id served at that endpoint.
- `api_key_env`: env var holding the credential, or `null` for a keyless local server (Ollama, vLLM without `--api-key`). Workers send a placeholder key such servers ignore.
- Names are slash-free aliases; `LLM_MODEL=<name>` selects them.

## Python workers

Set `LLM_MODEL=<name>` (and export the entry's key env var, if any). Explicit
constructor args and the driver's `agent_init` handoff still win — the
registry only fills in what they leave unset. `api_key_env` resolution falls
back through the normal chain (`LLM_API_KEY`, …), so an entry keeps working if
you later move its key into `LLM_API_KEY` instead.

## TUI planner (`ARGUS_PLANNER_MODEL`)

OpenCode cannot read the registry, so generate the provider block — e.g. with
a snippet evaluated from `src/argus/planner/custom-models.ts`
(`opencodeProviderSnippet`) — and paste it into `opencode.json`. The provider
id is namespaced `argus-<name>` so it never collides with your own providers.
Then select it with:

```sh
ARGUS_PLANNER_MODEL=argus-<name>/<model>
```

It becomes an ordinary configured provider: the existing selection policy,
`doctor` reporting, and ambient-env guard apply unchanged.

## Examples

The `examples` section of the registry shows the two common shapes (inert —
copy one into `models` to enable it): a keyless local Ollama model and a
keyed team vLLM endpoint.
