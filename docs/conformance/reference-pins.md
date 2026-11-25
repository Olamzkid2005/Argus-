# Upstream and baseline reference pins used for Stage 0

**Prepared:** 22 November 2026  
**Purpose:** Record the exact references consulted and used to initialize the
Stage 0 conformance artifacts. This is the “what did you actually pin” file,
not a claim that all downstream behaviours are implemented yet.

## 1. Primary source used for Stage 0

- **File:** `docs/conformance/argus_three_frameworks_implementation_conformance_plan.md`
- **Role:** Reference specification and conformance test list for the three
  proposed architectures (graph exploration, PentAGI, fact-and-intent).
- **What I used it for:**
  - Section 0: layered architecture decision and non-negotiable control rule
  - Section 2: existing Argus components to preserve and the authoritative-state
    constraint
  - Section 6.1–6.2: single dispatcher ownership and single top-level planner
  - Section 7.1–7.4: required verification protocol and minimum evidence
    artifacts
  - Section 9: explicit non-goals
  - Section 10: definition of done

## 2. Upstream pins recorded by the plan

These are the pins the plan says must be treated as source-locked. They were
**not fetched live for Stage 0**; they are recorded here as targets to consult
before implementing the corresponding behaviour.

| Project | Pinned commit | Primary files cited in the plan |
|---|---|---|
| Graph exploration reference | `94757c5d7e704ac1c095ee99e97d9ac4d9d428c5` | README, `agent/planner.go`, `db/exploration.go`, `db/assets.go`, `server/engine.go` |
| PentAGI | `cffed9485aa1cca70762cd08a57ac62a80406258` | `backend/docs/flow_execution.md`, `backend/pkg/providers/subtask_patch.go`, `backend/pkg/controller/subtask.go`, `backend/pkg/controller/task.go` |
| Fact-and-intent reference | `8e7e0ea67552383851dfcabfba0c4e9c8d007878` | `docs/specs/dispatcher-design.md`, `dispatcher/scheduler/loop.py`, `dispatcher/contracts.py`, `dispatcher/tasks/explore.py`, `dispatcher/tasks/reason.py` |
| Argus baseline | `0e006958927c82d95d293f4e08262df79d95e921` | README, `workflow-runner.ts`, `planner/executor.ts`, `mcp_server.py`, current gaps doc |

## 3. Local repository baseline actually inspected for Stage 0

- **Repository:** `Olamzkid2005/Argus-` (this checkout)
- **Current branch:** `freebuff/d05be3cea4e0f560a31b04f4`
- **Local files actually read:**
  - `docs/conformance/argus_three_frameworks_implementation_conformance_plan.md`
  - `Makefile`
  - `argus-workers/README.md`
  - `.github/workflows/lint.yml`

## 4. What Stage 0 does not claim

- It does not fetch the upstream commits listed above.
- It does not claim any `A-*`, `P-*`, or `C-*` requirement is implemented.
- It does not choose a final storage backend for service-backed deployments
  beyond what is already present in the repository.
