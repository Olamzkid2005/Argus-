# Cyber Harness Plan — Source of Truth

> Status: DRAFT, awaiting approval. No implementation until this doc is approved.
> Decided with user (2026-11-26): identity = **security console first**; agents = **keep generic + add security ones**; order = **all slices, most complex first**.

## 1. Overview

Convert the Opencode-based TUI from a generic coding harness into Argus: a
cybersecurity-focused console. Opening the app shows engagements and findings
first, chat second. Generic agents (`build`, `plan`, `explore`) stay; security
subagents (`recon`, `vuln-scan`, `verifier`, `reporter`) are added alongside.
Prompts, `AGENTS.md`, and docs are revoiced to cyber last (cheapest slice).

## 2. Architecture decisions (locked)

- AD-1: Console-first. `routes/home.tsx` defaults to engagements/findings
  summary; chat input stays but is secondary. Empty state points at `/scan`.
- AD-2: Additive agents. `src/agent/agent.ts` keeps `build`/`plan`/`general`/
  `explore` (and hidden `compaction`/`title`/`summary`). New native subagents:
  `recon`, `vuln-scan`, `verifier`, `reporter`. No deletions.
- AD-3: Permissions per role. Each security subagent gets a least-privilege
  allowlist in `agent.ts` + `subagent-permissions.ts`; `doctor` reports them.
  Resolved 2026-11-26: `vuln-scan` bash = auto-allow (user); `reporter`
  writes = evidence dir + reports/ (user); model selection unchanged (user).
- AD-4: Prompts are voice-only. Rewrites change wording and discipline
  (scope, evidence paths), never tool semantics.
- AD-5: Models unchanged structurally. `custom_models.json` + `ARGUS_PLANNER_MODEL`
  remains the free-limit escape hatch; this plan does not redesign model routing.
- AD-6: Order = most complex first: Phase 1 TUI → Phase 2 agents →
  Phase 3 prompts. Each phase leaves the app working and tested.

## 3. Task list

### Phase 1: TUI console-first (most complex — do first)

#### Task 1.1: Home defaults to engagements
**Description:** `routes/home.tsx` loads `EngagementStore.listEngagements()`
and renders targets/active/findings/critical-high-medium first; chat input
moves below. Empty state links to `/scan`, not "Ask anything".
**Acceptance criteria:**
- [ ] With engagements present, home shows counts + recent list without typing.
- [ ] With zero engagements, empty state names `/scan` explicitly.
- [ ] Per-engagement decrypt failure still shows the list (reuse 9d999d9e guard).
**Verification:**
- [ ] `bunx tsgo --noEmit` clean.
- [ ] Manual: fresh TUI shows console, not blank chat.
**Dependencies:** None.
**Files likely touched:**
- `Argus-Tui/packages/opencode/src/cli/cmd/tui/routes/home.tsx`
- `Argus-Tui/packages/opencode/src/argus/engagement/store.ts` (read-only usage)
**Estimated scope:** Medium (3–5 files).

#### Task 1.2: Scan + model surface in TUI
**Description:** Scan entry (`scan.tsx`, planner model id, custom-model snippet
hint) reachable from home so free-limit users find the OpenRouter path.
**Acceptance criteria:**
- [ ] Home links to scan flow in one keypress/click.
- [ ] Current planner model (`ARGUS_PLANNER_MODEL` or default) visible.
**Verification:**
- [ ] `bun test ./test/argus/unit/tui-commands.test.ts` passes.
- [ ] Manual: limit-hit user reaches the model hint in < 30s.
**Dependencies:** Task 1.1.
**Files likely touched:**
- `Argus-Tui/packages/opencode/src/cli/cmd/tui/routes/home.tsx`
- `Argus-Tui/packages/opencode/src/argus/tui/routes/scan.tsx`
- `Argus-Tui/packages/opencode/src/argus/tui/routes/dashboard.tsx`
**Estimated scope:** Small (1–2 files).

### Checkpoint: Phase 1
- [ ] `bunx tsgo --noEmit` clean.
- [ ] `bun test ./test/argus/unit/tui-commands.test.ts` passes.
- [ ] Human review of home screen before proceeding.

### Phase 2: Security agents + permissions

#### Task 2.1: Add `recon` + `vuln-scan` subagents
**Description:** Read-only recon (glob/grep/read/webfetch) and scanner
(tool-runner backed) subagents in `agent.ts` with cyber descriptions.
**Acceptance criteria:**
- [ ] `/agent` lists `recon`, `vuln-scan` as subagents.
- [ ] `recon` cannot edit files or run state-modifying bash; `vuln-scan`
  bash auto-allows (per user decision 2026-11-26).
**Verification:**
- [ ] `bun test ./test/agent/agent.test.ts` passes.
**Dependencies:** None (parallelizable with Phase 1).
**Files likely touched:**
- `Argus-Tui/packages/opencode/src/agent/agent.ts`
- `Argus-Tui/packages/opencode/test/agent/agent.test.ts`
**Estimated scope:** Small.

#### Task 2.2: Add `verifier` + `reporter` subagents
**Description:** Verifier re-tests candidate findings (evidence-required);
reporter writes findings/reports to evidence paths only.
**Acceptance criteria:**
- [ ] `verifier` cannot mark findings confirmed without evidence part.
- [ ] `reporter` can write only under the engagement evidence dir + reports/
  (per user decision 2026-11-26).
**Verification:**
- [ ] Agent permission tests pass.
**Dependencies:** Task 2.1 (same file, sequential).
**Files likely touched:**
- `Argus-Tui/packages/opencode/src/agent/agent.ts`
- `Argus-Tui/packages/opencode/src/agent/subagent-permissions.ts`
**Estimated scope:** Small.

#### Task 2.3: Doctor reports security allowlist
**Description:** `doctor` prints each security subagent and its allow/ask/deny
surface so permission drift is visible.
**Acceptance criteria:**
- [ ] `doctor` output names all four subagents with their tool classes.
**Verification:**
- [ ] Doctor unit tests pass.
**Dependencies:** Tasks 2.1–2.2.
**Files likely touched:**
- `Argus-Tui/packages/opencode/src/argus/commands/doctor.ts`
**Estimated scope:** Small.

### Checkpoint: Phase 2
- [ ] Agent tests + doctor tests pass.
- [ ] Human confirms role definitions before prompts work.

### Phase 3: Prompts + AGENTS.md (easiest — do last)

#### Task 3.1: Cyber prompts for new + kept agents
**Description:** New `src/agent/prompt/{recon,vuln-scan,verifier,reporter}.txt`;
rewrite `explore.txt` in cyber voice (scope discipline, absolute evidence
paths). Hidden `compaction`/`title`/`summary` revoiced without semantic change.
**Acceptance criteria:**
- [ ] Every visible agent resolves a prompt file.
- [ ] No tool semantics changed (diff shows wording only outside new files).
**Verification:**
- [ ] Prompt-loading tests pass; `tsgo --noEmit` clean.
**Dependencies:** Phase 2.
**Files likely touched:**
- `Argus-Tui/packages/opencode/src/agent/prompt/*`
- `Argus-Tui/packages/opencode/src/agent/agent.ts` (prompt wiring)
**Estimated scope:** Medium.

#### Task 3.2: Session prompt + `/init` template in cyber voice
**Description:** `src/session/prompt/default.txt` security framing (scope,
rules of engagement, evidence-first); `src/command/template/initialize.txt`
writes security `AGENTS.md`.
**Acceptance criteria:**
- [ ] `/init` on a fresh repo produces cyber `AGENTS.md` naming scope/evidence.
- [ ] Default session prompt mentions scope + evidence discipline.
**Verification:**
- [ ] Command template tests pass.
**Dependencies:** Task 3.1.
**Files likely touched:**
- `Argus-Tui/packages/opencode/src/session/prompt/default.txt`
- `Argus-Tui/packages/opencode/src/command/template/initialize.txt`
- `Argus-Tui/packages/opencode/src/session/instruction.ts` (only if loading changes; prefer no change)
**Estimated scope:** Small.

### Checkpoint: Complete
- [ ] `bunx tsgo --noEmit` clean.
- [ ] Agent + planner + tui-commands suites pass.
- [ ] One live `/scan` smoke on a lab target.
- [ ] Human approves voice before merge.

## 4. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| TUI-first churns the landing longest | Med | Phase 1 behind no flag but additive; chat input stays functional |
| Permission drift on new agents | High | Doctor reporting (Task 2.3) + permission unit tests |
| Prompt revoice changes behavior | Med | Wording-only diff rule; hidden agents semantics frozen |
| Single vs multiple security roles | Low | Locked AD-2 (additive); revisit only via doc amendment |

## 5. Open questions (resolved 2026-11-26)

- Q-1 (RESOLVED: auto-allow): `vuln-scan` bash auto-allows scanner commands.
- Q-2 (RESOLVED: evidence + reports): `reporter` writes under evidence dir + reports/.
- Q-3 (RESOLVED: don't change): model selection stays exactly as today.

## 6. Amendment log

| Date | Change | By |
|---|---|---|
| 2026-11-26 | Initial draft; locked identity/agents/order per user answers | joint |
| 2026-11-26 | Resolved Q-1 (auto-allow scan), Q-2 (evidence+reports), Q-3 (models unchanged) | user answers |
