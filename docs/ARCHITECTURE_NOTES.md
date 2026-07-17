# Architecture Notes & Design Decisions

> **Purpose:** Record architectural decisions, confirmed intentional absences, and resolved investigations for the engineering team.
> **Last updated:** 2026-07-17

---

## 1. `pause_project` / Infra-Lifecycle — Intentionally Absent

**Status:** ✅ Confirmed absent by design

After an exhaustive codebase search, no `pause_project`, `infra_lifecycle`, or similar engagement-pausing functionality was found anywhere in the codebase.

### Rationale

The Argus engagement lifecycle is intentionally **fire-and-forget**:

| Phase | State | Description |
|-------|-------|-------------|
| `pending` | Initial | Engagement created, not yet started |
| `running` | Active | Orchestrator actively executing tools |
| `complete` | Terminal | All phases completed successfully |
| `failed`  | Terminal | Fatal error during execution |

There is intentionally **no `paused` state** for the full engagement lifecycle because:

1. **Tool externalities:** Most security tools (nuclei, sqlmap, dalfox) do not support pausing mid-execution. Killing and resuming them would lose state.
2. **Checkpoint-based resume:** Instead of pausing, Argus uses per-tool-call checkpointing (`checkpoint_manager.py`). Completed tools are skipped on resume. This is more reliable than process-level suspension.
3. **Cost control:** LLM budget tracking (`LlmCostTracker`, `governance.py`) handles cost limits by preventing new LLM calls — no need to pause the engagement.
4. **Simplicity:** Eliminates an entire category of edge cases (what happens if a tool completes during pause? does the orchestrator heartbeat while paused? etc.)

### If pause were needed

If a future requirement demands engagement pausing, the implementation should:

1. Add a `paused` state to `EngagementStateMachine` in `state_machine.py`
2. Add `pause_engagement` / `resume_engagement` endpoints to the orchestrator
3. After resume, use existing `checkpoint_manager.get_resume_plan()` to determine which tools need re-execution
4. Cap paused duration (e.g., 24h auto-resume or auto-fail) to prevent abandoned paused engagements

---

## 2. Slash-Command Bleed — No Vulnerability Found

**Status:** ❌ Refuted — no evidence of slash-command bleed vulnerability

### Investigation

The audit item "Verify the slash-command bleed fix actually landed" was investigated across the entire TUI codebase.

**What was examined:**

- `Argus-Tui/packages/opencode/src/argus/intent-classifier.ts` — Classifies user input. Slash commands (`/scan`, `/assess`, `/recon`, etc.) are detected via `classifyIntent()` which checks for leading `/` and maps to the `ArgusCommandRouter`. Non-slash-command input flows to natural language processing. No bleed path exists.
- `Argus-Tui/packages/opencode/src/argus/tui-commands.ts` — Defines `ArgusTuiCommands` and `findArgusTuiCommand()`. Commands are explicitly enumerated; there is no fallback that could interpret non-command input as a command.
- `Argus-Tui/packages/opencode/src/argus/agent.ts` — `ArgusCommandRouter` handles slash commands distinctly from tool execution. Commands like `/status`, `/doctor` have separate handler paths.
- `Argus-Tui/packages/opencode/src/project/project.ts` — The `/init` slash command subscription is isolated to a per-instance handler.

**Conclusion:** The slash-command classification is strict — a leading `/` is required, and the command must match an enumerated list. There is no path where natural language input could be misinterpreted as a slash command, or where user input from one context (e.g., a chat message) could bleed into another context's command processing.

### Note on the original claim

The original claim that a "slash-command bleed fix" needed to "land" may refer to a pre-audit state that has since been resolved by the `intent-classifier.ts` implementation (which is the current codebase state). No remnant of a bleed vulnerability was found.

---

## 3. Subprocess Sandbox Isolation — Future Work

**Status:** 🔍 Documented gap — see `docs/sandbox-isolation-plan.md`

The `chain_exploit_generator.py` uses `subprocess.run()` with `shell=False` and a locked-down environment (blocked env vars) for verifying chain exploit scripts. This is adequate for the current threat model but could be hardened with Docker container isolation. See the sandbox isolation plan document for the full design.

---

## 4. Thread Safety Model

The DI container (`di_container.py`) uses:

- **Module-level lock** (`_containers_lock`): Protects the global `_containers` dict
- **Per-container lock** (`self._lock`): Double-checked locking on lazy-init properties (`tool_runner`, `llm_client`, `checkpoint_manager`)
- **Closed guard** (`self._closed`): Prevents use of a closed container

This model supports concurrent access across engagements while preventing data races.

---

## 5. LLM Data Sanitization Architecture

The `_sanitize_for_llm()` function in `agent_prompts.py` is the **single entry point** for all external data entering LLM context. It applies:

1. **Truncation** to 3000 chars (limits context window abuse)
2. **Control character stripping** (prevents ANSI escape injection)
3. **Backtick fence replacement** (` ``` ` → `` ` ` ` ``) — prevents prompt structure breakage
4. **Prompt injection pattern redaction** — regex-based, 8 patterns covering system prompt overrides, command injections, and tool execution attempts
5. **Secret/credential redaction** — 40+ patterns covering API keys, tokens, passwords, private keys, database URLs, cloud credentials

**Known limitation:** Regex-based defenses are bypassable by novel phrasing. See `test_sanitize_for_llm_adversarial.py` for adversarial test vectors.
