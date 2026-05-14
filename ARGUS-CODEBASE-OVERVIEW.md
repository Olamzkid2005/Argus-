# Argus SOC Platform — Complete Codebase Overview

## What is Argus?

Argus is an **AI-powered cybersecurity operations center (SOC) platform for autonomous penetration testing**. It automates end-to-end security assessments through a multi-stage pipeline: users create engagements → background Celery workers run reconnaissance, vulnerability scanning, and AI-powered analysis → findings stream back to the frontend in real time via SSE/WebSocket.

---

## Repository Structure

```
/Users/mac/Documents/Argus-/
├── argus-platform/          # Next.js 14 frontend + API (TypeScript)
├── argus-workers/           # Python worker system (Celery)
├── deployment/              # Caddy & Nginx reverse proxy configs
├── docs/                    # Architecture docs, setup guides
├── start-argus.sh           # Start all services
├── stop-argus.sh            # Stop all services
└── Makefile                 # Dev, test, lint, build, docker, db commands
```

---

## Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                     argus-platform/ (Next.js 14)                    │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌───────────────────┐ │
│  │ src/app/ │  │src/lib/  │  │ src/hooks/│  │ src/components/   │ │
│  │ (pages)  │  │ (utils)  │  │ (React)   │  │ (UI + custom)     │ │
│  └────┬─────┘  └────┬─────┘  └───────────┘  └───────────────────┘ │
│       │             │                                              │
│  ┌────▼─────────────▼─────┐                                        │
│  │   API Routes (27 dirs) │  ← REST + SSE + WebSocket              │
│  └──────────┬─────────────┘                                        │
└─────────────┼───────────────────────────────────────────────────────┘
              │
    ┌─────────▼──────────┐       ┌──────────────────┐
    │    PostgreSQL 15    │       │   Redis (Broker)  │
    │  (pgvector, JSONB)  │       │  Cache / Pub-Sub  │
    └─────────┬──────────┘       └────────┬─────────┘
              │                           │
              │                    ┌──────▼──────────┐
              │                    │  Celery Workers  │◄── Celery Beat
              │                    │  (argus-workers/) │    (scheduler)
              │                    └──────┬───────────┘
              │                           │
              │       ┌───────────────────┼───────────────────┐
              │       │                   │                   │
              │  ┌────▼─────┐   ┌────────▼───────┐   ┌──────▼──────┐
              │  │  Recon   │   │     Scan       │   │   Analyze   │
              │  │ subfinder│   │ nuclei, sqlmap │   │ AI-powered  │
              │  │ httpx..  │   │ ffuf, dalfox.. │   │ dedup/score │
              │  └──────────┘   └────────────────┘   └─────────────┘
              │                           │
              └───────────────────────────┘
                   25+ Security Tools
```

---

## Stack Summary

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind CSS, Radix UI, Framer Motion, Recharts, Three.js, React Query |
| API | Next.js API Routes, NextAuth.js, Upstash Redis (rate limiting) |
| Auth | NextAuth.js with credentials + OAuth (Google, GitHub), bcryptjs, account lockout |
| Workers | Python 3.11+, Celery 5.4 (with Redis broker), Celery Beat |
| Database | PostgreSQL 15 + pgvector + pgcrypto + uuid-ossp |
| Cache/Queue | Redis (broker, caching, pub/sub, DLQ, idempotency) |
| AI/LLM | OpenRouter API (Anthropic, OpenAI, Google, Meta, DeepSeek, Mistral, Qwen, NVIDIA, Perplexity) |
| Security Tools | Nuclei, httpx, subfinder, ffuf, sqlmap, Katana, Naabu, Amass, Dalfox, Nikto, Semgrep, Bandit, Gitleaks, Trivy, WhatWeb, WPScan, Arjun, Commix, JWT_Tool, GAU, Waybackurls, Gospider, AlterX, TestSSL, pip-audit |

---

## argus-platform/ — Next.js Frontend & API

### Entry Point
- `npm run dev` → `next dev` on port 3000
- `npm run build` → production build
- `npm test` → Jest + Playwright

### src/app/ — App Router Pages
All pages use Next.js 14 App Router with server components, streaming, and parallel routes:
- Landing page, Dashboard, Engagements (CRUD), Findings (realtime), Analytics (charts), Reports (PDF/HTML/JSON), Settings, Rules, Assets, Auth (login/signup/OAuth), Monitoring, System health, API docs

### src/app/api/ — 27 API Route Groups
```
admin/         ai/          analytics/    assets/
auth/          dashboard/   db/
engagement/    engagements/  findings/     health/
logs/          monitoring/   observability/ openapi/
org/           reports/      rules/        security-rating/
settings/      stream/       system/       tools/
v2/            webhooks/     ws/
```
Pattern: Each is a Next.js Route Handler (export async function GET/POST/PUT/DELETE).
Real-time: SSE endpoints in `stream/`, WebSocket upgrade in `ws/`.

### src/lib/ — 34 Shared Utilities
| File | Purpose |
|------|---------|
| auth.ts | NextAuth configuration, JWT/session callbacks, credential + OAuth providers |
| db.ts | PostgreSQL connection pool (pg), parameterized queries |
| redis.ts | ioredis client, job queuing helpers, pub/sub |
| websocket.ts | ResilientWebSocket with automatic SSE polling fallback |
| rate-limiter.ts | Upstash Redis sliding window rate limiting |
| audit-logging.ts | Structured audit trail |
| validation.ts | Zod schemas for all API inputs |
| caching.ts | Response caching layer |
| security-rating.ts | Security posture scoring |
| job-types.ts | TypeScript mirror of Python's job_schema.py (shared contract) |
| email.ts | Nodemailer email sending |
| sanitize.ts | XSS/HTML sanitization |
| constants.ts | App-wide constants |
| logger.ts | Structured logging |

### src/components/ — UI Layer
- **ui/** (61 components) — Radix UI primitives: Button, Dialog, DropdownMenu, Select, Tabs, Toast, Tooltip, Table, Form, Calendar, Command, Popover, etc.
- **ui-custom/** (20 components) — Bespoke components: AttackPathGraph, ExecutionTimeline, ScannerActivityPanel, Sidebar, CommandPalette, StatusBadge, FindingsTable, EngagementCard, etc.
- **animations/** — Framer Motion animation components
- **effects/** — SurveillanceEye (Three.js 3D visual)
- **security/** — Security-specific UI components

### src/hooks/ — React Hooks
use-engagement-events, use-scanner-activities, useRequireAuth, useMobileDetect, useNotifications, useScanEstimates, useThemeColors, useKeyboardShortcuts

### src/middleware.ts
Security headers (CSP, HSTS, X-Frame-Options), rate limiting (Upstash Redis sliding window), API versioning, audit logging on every request.

### db/ — Database
- schema.sql — Full PostgreSQL schema (engagements, findings, users, teams, rules, assets, reports, audit_logs, etc.)
- migrations/ — Versioned SQL migrations
- Setup/verify/optimization scripts

### tests/ — Test Suite
Jest (unit/integration) + Playwright (E2E browser tests)

---

## argus-workers/ — Python Worker System

### Entry Points
- `celery -A celery_app worker -Q recon,scan,analyze,report,repo_scan` — Start workers
- `celery -A celery_app beat` — Start scheduler
- Queue routing: recon → scan → analyze → report (chained tasks)

### celery_app.py — Celery Configuration
- Redis broker & result backend
- Task routes: 5 queues (recon, scan, analyze, report, repo_scan)
- Beat schedule: scheduled scans every 5min, cleanup, health checks, nuclei template updates
- BaseTask with DLQ support, retry logic, graceful shutdown, error classification

### job_schema.py — Shared Job Contract (Python ↔ TypeScript)
- `JobMessage` dataclass — standard job payload
- `TASK_NAME_MAP` — maps job types to Celery task names
- `build_task_args()` — constructs task arguments
- Mirrored in TypeScript as `src/lib/job-types.ts`

### pipeline_router.py — Pipeline Entry Point
Routes incoming jobs to `orchestrator_pkg/recon.py` and `orchestrator_pkg/scan.py`

### orchestrator_pkg/ — Execution Engine
| File | Purpose |
|------|---------|
| orchestrator.py | Orchestrator class — workflow executor, manages tool execution lifecycle |
| recon.py | Runs reconnaissance tools (subfinder, httpx, katana, amass, naabu, gau, waybackurls, gospider, alterx, whatweb) |
| scan.py | Runs vulnerability scanning tools (nuclei, sqlmap, ffuf, dalfox, nikto, wpscan, arjun, commix, jwt_tool, testssl) |
| repo_scan.py | Code repository scanning (semgrep, bandit, gitleaks, trivy, pip-audit) |
| utils.py | Shared orchestrator utilities |

### tools/ — 25+ Security Tool Wrappers + Infrastructure
| File | Purpose |
|------|---------|
| tool_runner.py | Sandboxed subprocess execution with timeout, env isolation |
| tool_executor.py | End-to-end tool execution flow (fetch → run → parse → store) |
| context.py | ToolContext dataclass for dependency injection |
| circuit_breaker.py | Prevents hammering failing tools |
| tool_result.py | ToolResult typed dataclass (stdout, stderr, exit_code, duration, artifacts) |
| web_scanner.py | Custom web vulnerability scanner |
| api_scanner.py | API endpoint security scanner |
| browser_scanner.py | Browser-based dynamic scanning |
| websocket_scanner.py | WebSocket endpoint security testing |
| container_scanner.py | Container image vulnerability scanning |
| port_scanner.py | Network port scanning |
| scope_validator.py | Ensures scans stay within defined scope |
| finding_verifier.py | Secondary verification of findings |
| llm_payload_generator.py | AI-generated attack payloads |
| llm_detector.py | AI-powered vulnerability detection |
| auth_manager.py | Authentication state management for authenticated scanning |
| sbom_generator.py | Software Bill of Materials generation |
| bugbounty_report_generator.py | Bug bounty platform report formatting |
| mcp_bridge.py | Model Context Protocol bridge for standardized tool calling |
| tool_cache.py | Tool result caching |

### parsers/ — 28 Output Parsers (Auto-Discovered)
```
base.py           # Abstract BaseParser class
parser.py         # Main Parser — routes tool output to correct parser, span tracing
normalizer.py     # FindingNormalizer — normalizes raw to VulnerabilityFinding

nuclei.py         httpx.py          sqlmap.py         ffuf.py
subfinder.py      amass.py          katana.py         dalfox.py
nikto.py          semgrep.py        bandit.py         gitleaks.py
trivy.py          whatweb.py        wpscan.py         arjun.py
commix.py         jwt_tool.py       naabu.py          gau.py
waybackurls.py    gospider.py       alterx.py         testssl.py
pip_audit.py      web_scanner.py
```

Auto-registration pattern: add a new parser file, it's automatically discovered and registered. No config changes needed.

### agent/ — LLM ReAct Agent (Autonomous Decision-Making)
| File | Purpose |
|------|---------|
| react_agent.py | ReAct loop: LLM observes → picks tool → executes → observes result → repeats |
| tool_registry.py | Registers available tools for the agent |
| agent_action.py | Action model for agent decisions |
| agent_result.py | Result model for agent observations |
| agent_prompts.py | System prompts for the LLM agent |
| agent_config.py | Agent configuration (model, temperature, max iterations) |
| coordinator.py | Multi-agent coordination |
| swarm.py | Agent swarm for parallel tool execution |
| bugbounty_knowledge/ | Bug bounty hunting knowledge base |

### models/ — Pydantic Data Models
| File | Purpose |
|------|---------|
| finding.py | VulnerabilityFinding (id, severity, title, description, cvss, evidence, remediation) |
| recon_context.py | ReconContext (discovered hosts, ports, services, technologies) |
| candidate_list.py | Candidate finding list for prioritization |
| confidence_scorer.py | Confidence scoring for findings |
| feedback.py | User feedback on findings |

### database/ — DB Access Layer
- connection.py — Singleton ConnectionManager with thread-safe connection pool, PgBouncer support, slow query logging
- repositories/ — 14 repository classes:
  - engagement, finding, report, tool_metrics, tracing, agent_decision
  - ai_explainability, engagement_events, pgvector, rate_limit
  - target_profile, tool_accuracy

### Core Engine Files
| File | Purpose |
|------|---------|
| intelligence_engine.py | Decision-making core: confidence scoring, false-positive detection, finding deduplication, attack path construction, findings prioritization by signal quality |
| state_machine.py | EngagementStateMachine — enforces valid state transitions (created → recon → scanning → analyzing → reporting → complete/failed) |
| attack_graph.py | Attack graph engine with Bug-Reaper vulnerability chaining templates |
| llm_client.py | Unified LLM client: OpenAI SDK + generic HTTP API, multi-provider (OpenRouter), cost tracking |
| llm_service.py | Higher-level LLM service with JSON parsing, schema validation, retry, cost enforcement |
| llm_synthesizer.py | LLM synthesis of findings into reports |
| llm_report_generator.py | Generates PDF/HTML/JSON reports |
| ai_explainer.py | AI explanations for findings (constrained — no decision-making) |
| cvss_calculator.py | CVSS v3.1 auto-calculation |
| tool_definitions.py | Single source of truth for all tool metadata, phases, timeouts, signal quality tiers |

### Operational Infrastructure
| File | Purpose |
|------|---------|
| streaming.py | Unified EventBus: SSE + Redis pub/sub adapters, emit_*() convenience functions |
| websocket_events.py | WebSocketEventPublisher — publishes real-time events to Redis for frontend polling |
| dead_letter_queue.py | DLQ: stores failed tasks in Redis, supports replay |
| tracing.py | Execution span tracing + structured logging |
| health_monitor.py | Worker health monitoring |
| shutdown_handler.py | Graceful shutdown handling |
| autoscale.py | Dynamic worker autoscaling |
| distributed_lock.py | Redis-backed distributed locking |
| feature_flags.py | Feature flag system |
| checkpoint_manager.py | Pipeline checkpoint/resume |
| snapshot_manager.py | System state snapshots |
| mcp_server.py | Model Context Protocol server |

---

## Engagement Lifecycle (End-to-End Data Flow)

1. **User creates engagement** via Next.js UI
   → `POST /api/engagement/create`
   → Insert into PostgreSQL (engagements table)
   → Dispatch `JobMessage` to Redis

2. **Celery worker picks up** `tasks.recon.run_recon`
   → `Orchestrator.run_recon()`
   → Executes recon tools: subfinder, httpx, katana, amass, naabu, gau, waybackurls, gospider, alterx, whatweb
   → Parses output via 28 parsers
   → Stores ReconContext in PostgreSQL
   → Pushes events via WebSocketEventPublisher → Redis → Frontend SSE

3. **Recon complete** → worker chains `tasks.scan.run_scan`
   → `Orchestrator.run_scan()`
   → Executes scan tools: nuclei, sqlmap, ffuf, dalfox, nikto, wpscan, arjun, commix, jwt_tool, testssl
   → Parses output → normalizes to VulnerabilityFinding
   → Stores findings in PostgreSQL (with pgvector embeddings)
   → Pushes real-time events to frontend

4. **Scan complete** → worker chains `tasks.analyze.run_analysis`
   → `IntelligenceEngine` processes findings:
     - Confidence scoring
     - False-positive detection
     - Finding deduplication (across tools)
     - Attack path construction
     - Prioritization by signal quality tier
   → `ai_explainer.py` generates human-readable explanations
   → `cvss_calculator.py` computes CVSS scores

5. **Analysis complete** → worker chains `tasks.report.generate_report`
   → `llm_synthesizer.py` synthesizes findings
   → `llm_report_generator.py` generates PDF/HTML/JSON report
   → Stores report in PostgreSQL
   → Engagement status → "complete"

6. **Throughout lifecycle**:
   - `EngagementStateMachine` enforces valid transitions
   - `WebSocketEventPublisher` pushes events to Redis
   - Frontend polls/SSEs for real-time updates
   - Failures go to DLQ for inspection/replay
   - `ExecutionTimeline` shows step-by-step progress

---

## Key Design Patterns

### Shared Schema Contract
`job_schema.py` (Python) ↔ `job-types.ts` (TypeScript) — ensures frontend and workers speak the same language. When a job type is added, both files must be updated.

### Parser Auto-Discovery
28 parsers in `parsers/parsers/` auto-register via `__init__.py` introspection. Adding support for a new tool = creating one new parser file. No config, no registration.

### Dependency Injection
`ToolContext` dataclass replaces direct Orchestrator access. Tools receive only what they need (db connection, redis client, LLM client, etc.) — not the whole Orchestrator.

### Signal Quality Tiers
Findings categorized: confirmed > probable > candidate. Analysis budget allocated proportionally. High-signal findings get deep analysis; low-signal get basic triage.

### Circuit Breaker + DLQ
Tools that fail repeatedly are circuit-broken (stopped temporarily). All failed tasks go to Dead Letter Queue in Redis with full context for later replay.

### ReAct Agent Pattern
LLM observes the engagement state → decides which tool to run → executes it → observes results → decides next action. Autonomous tool selection without hardcoded playbooks.

### State Machine
`EngagementStateMachine` is the single authority on engagement status. No code can transition an engagement to an invalid state.

### Feature Flags
`feature_flags.py` gates experimental features (new parsers, agent modes, tool integrations) behind flags. Safe to ship code before it's fully ready.

---

## How to Run Locally

```bash
# Start all services
./start-argus.sh

# Or manually:
# 1. PostgreSQL + Redis must be running
# 2. Frontend:
cd argus-platform && npm run dev    # port 3000

# 3. Workers:
cd argus-workers && celery -A celery_app worker -Q recon,scan,analyze,report,repo_scan

# 4. Scheduler:
cd argus-workers && celery -A celery_app beat
```

---

## File Count & Scale
- **TypeScript files**: ~200+ (argus-platform)
- **Python files**: ~150+ (argus-workers)
- **API route groups**: 27
- **Celery task modules**: 19
- **Security tools integrated**: 25+
- **Output parsers**: 28
- **UI components**: 81 (61 Radix + 20 custom)
- **DB repositories**: 14
- **React hooks**: 8
- **Shared lib utilities**: 34
