// Gate A driver: three cold `argus` -> `/assess <lab>` cycles through the TUI in
// a real PTY, against the provisioned PostgreSQL + Redis + Celery worker + LLM
// stack. Each run gets a fresh HOME (cold start), its own engagement, a JSON
// record and the raw PTY transcript.
//
// The TUI keeps engagements in SQLite (`ENG-*`), while the worker's scope guard
// loads `authorized_scope` from PostgreSQL by UUID, so worker tools are refused
// for a TUI-created engagement. The declared allowlist is the scope: the
// development escape hatch that lets a lab run execute tools regardless; it is
// inherited only by the MCP server this run spawns, and the TypeScript side still
// enforces ARGUS_SCOPE_MODE=allowlist for 127.0.0.1.
//
// Prerequisites: the stack described in README.md (PostgreSQL, Redis, the
// Celery worker, the lab target) plus an OpenAI-compatible endpoint at
// GATE_A_LLM_URL. Usage: RUNS=3 bun run scripts/livefire/gate-a.ts
// Results land in livefire-runs/gate-a-<stamp>/ (gitignored).
import path from "node:path"
import { appendFileSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { Database } from "bun:sqlite"

const REPO = path.resolve(import.meta.dir, "../..")
const TUI = path.join(REPO, "Argus-Tui/packages/opencode")
const PYTHON = path.join(REPO, "argus-workers/venv/bin/python")
const PG_LIB = path.join(REPO, "argus-workers/venv/lib/python3.12/site-packages/pgserver/pginstall/lib")
const TARGET = process.env.GATE_A_TARGET ?? "http://127.0.0.1:18080"
const RUNS = Number(process.env.RUNS ?? 3)
const TIMEOUT_SECONDS = Number(process.env.TIMEOUT_SECONDS ?? 1500)
const LLM_URL = process.env.GATE_A_LLM_URL ?? "http://127.0.0.1:18081/v1"

const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19)
const outDir = path.join(REPO, "livefire-runs", `gate-a-${stamp}`)
mkdirSync(outDir, { recursive: true })

const baseEnv: Record<string, string> = {
  PATH: `${path.join(REPO, ".livefire/bin")}:${path.join(REPO, "argus-workers/venv/bin")}:${process.env.PATH ?? ""}`,
  DATABASE_URL: "postgresql://argus_user@127.0.0.1:5432/argus_pentest",
  REDIS_URL: "redis://:argus-livefire-redis@127.0.0.1:6379/0",
  CELERY_BROKER_URL: "redis://:argus-livefire-redis@127.0.0.1:6379/0",
  CELERY_RESULT_BACKEND: "redis://:argus-livefire-redis@127.0.0.1:6379/1",
  LLM_PROVIDER: "generic",
  LLM_API_URL: "http://127.0.0.1:18081/v1/chat/completions",
  LLM_API_KEY: "livefire-stub",
  LLM_MODEL: "gpt-4o-mini",
  ARGUS_ALLOW_INTERNAL_TARGETS: "1",
  ARGUS_AUTONOMOUS: "1",
  // Autonomous mode is fail-closed until the authorized scope is declared (the
  // committed config ships mode: warn).
  ARGUS_SCOPE_MODE: "allowlist",
  ARGUS_ALLOWED_TARGETS: "127.0.0.1",
  // Unattended runs cannot answer the destructive-tool prompt; this approves it
  // with an auditable "auto-approved at <timestamp>" record instead.
  ARGUS_AUTO_APPROVE: "1",
  ARGUS_ALLOW_AMBIENT_LLM_ENV: "0",
  ARGUS_LLM_TRANSPORT: "direct",
  ARGUS_PYTHON: PYTHON,
  ARGUS_NUCLEI_TEMPLATES: "/workspace/homes/d05be3cea4e0f560a31b04f4/nuclei-templates",
  LD_LIBRARY_PATH: PG_LIB,
  TERM: "xterm-256color",
  OPENCODE_DISABLE_PROJECT_CONFIG: "1",
  OPENCODE_DISABLE_AUTOUPDATE: "1",
  OPENCODE_DISABLE_MODELS_FETCH: "1",
  OPENCODE_PURE: "1",
  OPENCODE_MODELS_PATH: path.join(TUI, "test/tool/fixtures/models-api.json"),
  OPENCODE_AUTH_CONTENT: "{}",
  OPENCODE_DB: ":memory:",
}

const provider = {
  formatter: false,
  lsp: false,
  provider: {
    test: {
      name: "Test",
      id: "test",
      env: [],
      npm: "@ai-sdk/openai-compatible",
      models: {
        "test-model": {
          id: "test-model",
          name: "Test Model",
          attachment: false,
          reasoning: false,
          temperature: false,
          tool_call: true,
          release_date: "2025-01-01",
          limit: { context: 100_000, output: 10_000 },
          cost: { input: 0, output: 0 },
          options: {},
        },
      },
      options: { apiKey: "livefire-stub", baseURL: LLM_URL },
    },
  },
  model: "test/test-model",
  enabled_providers: ["test"],
}

type RunRecord = {
  run: number
  startedAt: string
  target: string
  coldHome: string
  promptMs: number | null
  assessmentStartedMs: number | null
  finishedAtMs: number | null
  outcome: string | null
  engagementId: string | null
  status: string | null
  findings: number | null
  severity: Record<string, number> | null
  exitCode: number | null
  timedOut: boolean
  transcript: string
}

function readEngagement(home: string) {
  const root = path.join(home, "argus/argus.db")
  let engagement: { id: string; target: string; status: string } | null = null
  try {
    const db = new Database(root, { readonly: true })
    engagement = (db.query("SELECT id, target, status FROM engagements ORDER BY created_at DESC LIMIT 1").get() as any) ?? null
    db.close()
  } catch {}
  if (!engagement) return { engagement: null, findings: null, severity: null }

  let findings: number | null = null
  let severity: Record<string, number> | null = null
  try {
    const db = new Database(path.join(home, `argus/engagements/${engagement.id}/engagement.db`), { readonly: true })
    const tables = db.query("SELECT name FROM sqlite_master WHERE type='table'").all() as Array<{ name: string }>
    if (tables.some((t) => t.name === "findings")) {
      findings = Number((db.query("SELECT count(*) AS c FROM findings").get() as any).c)
      severity = {}
      for (const row of db.query("SELECT severity, count(*) AS c FROM findings GROUP BY severity").all() as any[]) {
        severity[String(row.severity)] = Number(row.c)
      }
    }
    db.close()
  } catch {}
  return { engagement, findings, severity }
}

const results: RunRecord[] = []

for (let run = 1; run <= RUNS; run++) {
  const home = mkdtempSync(path.join(tmpdir(), `gate-a-${run}-`))
  mkdirSync(path.join(home, "argus"), { recursive: true })
  writeFileSync(path.join(home, "argus/config.yaml"), "storage:\n  encryption:\n    enabled: false\n")
  const transcript = path.join(outDir, `run-${run}.pty.log`)
  writeFileSync(transcript, "")

  const decoder = new TextDecoder()
  let window = ""
  let promptMs: number | null = null
  let finishedAtMs: number | null = null
  const started = Date.now()
  const record: RunRecord = {
    run,
    startedAt: new Date().toISOString(),
    target: TARGET,
    coldHome: home,
    promptMs: null,
    assessmentStartedMs: null,
    finishedAtMs: null,
    outcome: null,
    engagementId: null,
    status: null,
    findings: null,
    severity: null,
    exitCode: null,
    timedOut: false,
    transcript,
  }

  const terminal = new Bun.Terminal({
    cols: 120,
    rows: 50,
    data(_, bytes) {
      const text = decoder.decode(bytes, { stream: true })
      appendFileSync(transcript, text)
      window = (window + text).slice(-32_768)
      if (promptMs === null && window.includes("/assess")) promptMs = Date.now() - started
      if (finishedAtMs === null) {
        const match = window.match(/Assessment (complete|finished|failed)/)
        if (match) {
          finishedAtMs = Date.now() - started
          record.outcome = match[1]
        }
      }
    },
  })

  console.log(`[gate-a] run ${run}/${RUNS} cold start in ${home}`)
  const child = Bun.spawn([process.execPath, path.join(TUI, "bin/argus")], {
    cwd: REPO,
    terminal,
    env: { ...baseEnv, HOME: home, ARGUS_DATA_DIR: path.join(home, "argus"), OPENCODE_CONFIG_CONTENT: JSON.stringify(provider) },
  })

  for (let i = 0; i < 600 && promptMs === null; i++) {
    if (child.exitCode !== null) break
    await Bun.sleep(100)
  }
  record.promptMs = promptMs
  console.log(`[gate-a] run ${run}: prompt at ${promptMs}ms`)

  if (promptMs !== null) {
    terminal.write(`/assess ${TARGET}`)
    await Bun.sleep(100)
    terminal.write("\r")
    record.assessmentStartedMs = Date.now() - started
  }

  const deadline = Date.now() + TIMEOUT_SECONDS * 1000
  while (finishedAtMs === null && Date.now() < deadline && child.exitCode === null) await Bun.sleep(1000)
  record.timedOut = finishedAtMs === null && child.exitCode === null
  record.finishedAtMs = finishedAtMs

  // Give the report phase a moment to persist before reading the store.
  await Bun.sleep(3000)
  const { engagement, findings, severity } = readEngagement(home)
  record.engagementId = engagement?.id ?? null
  record.status = engagement?.status ?? null
  record.findings = findings
  record.severity = severity

  if (child.exitCode === null) {
    terminal.write("/exit")
    await Bun.sleep(100)
    terminal.write("\r")
    await Promise.race([child.exited, Bun.sleep(20_000)])
  }
  if (child.exitCode === null) child.kill("SIGTERM")
  await Promise.race([child.exited.catch(() => {}), Bun.sleep(10_000)])
  if (child.exitCode === null) child.kill("SIGKILL")
  record.exitCode = child.exitCode
  try {
    terminal.close()
  } catch {}

  results.push(record)
  writeFileSync(path.join(outDir, `run-${run}.json`), JSON.stringify(record, null, 2))
  console.log(
    `[gate-a] run ${run}: outcome=${record.outcome} status=${record.status} findings=${record.findings} at ${record.finishedAtMs}ms exit=${record.exitCode}`,
  )
}

const passed = results.every((r) => r.outcome === "complete" && r.promptMs !== null && r.exitCode === 0)
writeFileSync(
  path.join(outDir, "summary.json"),
  JSON.stringify({ target: TARGET, runs: results.length, passed, results }, null, 2),
)
console.log(`[gate-a] DONE passed=${passed} dir=${outDir}`)
process.exit(passed ? 0 : 1)
