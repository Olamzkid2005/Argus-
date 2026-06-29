/**
 * Docker Lifecycle Helpers — E2E test infrastructure (Task 4.3).
 *
 * Provides utilities for starting/stopping vulnerable test targets
 * (Juice Shop, DVWA) via Docker Compose and waiting for them to become
 * healthy before running assessments against them.
 *
 * Usage:
 *   import { startTargets, stopTargets, waitForTarget } from "./docker-helpers"
 *
 *   beforeAll(async () => { await startTargets(); await waitForTarget(juiceShopURL) })
 *   afterAll(async () => { await stopTargets() })
 */

import { spawn, type ChildProcess } from "node:child_process"
import { setTimeout as sleep } from "node:timers/promises"

// ── Public API ───────────────────────────────────────────────────────────────

export interface TargetDefinition {
  name: string
  url: string
  healthEndpoint?: string
  maxRetries?: number
  retryDelayMs?: number
}

export const JUICE_SHOP: TargetDefinition = {
  name: "juice-shop",
  url: "http://127.0.0.1:3001",
  healthEndpoint: "http://127.0.0.1:3001",
  maxRetries: 30,
  retryDelayMs: 2000,
}

export const DVWA: TargetDefinition = {
  name: "dvwa",
  url: "http://127.0.0.1:3002",
  healthEndpoint: "http://127.0.0.1:3002/login.php",
  maxRetries: 30,
  retryDelayMs: 2000,
}

/**
 * Start vulnerable test targets via Docker Compose.
 * Uses the `e2e` profile defined in the root docker-compose.yml.
 *
 * Returns a promise that resolves once all container processes have been spawned.
 * Use `waitForTarget()` to wait for HTTP readiness.
 */
export async function startTargets(targets?: string[]): Promise<void> {
  const services = targets?.join(" ") ?? "juice-shop dvwa"
  const projectDir = projectRoot()

  await runCommand("docker", ["compose", "--profile", "e2e", "up", "-d", ...(targets ?? ["juice-shop", "dvwa"])], {
    cwd: projectDir,
    description: `Start Docker targets: ${services}`,
  })
}

/**
 * Stop and remove vulnerable test targets, preserving data volumes.
 */
export async function stopTargets(targets?: string[]): Promise<void> {
  const projectDir = projectRoot()
  const services = targets?.join(" ") ?? "juice-shop dvwa"

  await runCommand("docker", ["compose", "--profile", "e2e", "down", ...(targets ?? [])], {
    cwd: projectDir,
    description: `Stop Docker targets: ${services}`,
  })
}

/**
 * Wait for a target to respond to HTTP requests.
 * Polls the health endpoint until it returns a 2xx status or retries are exhausted.
 *
 * @throws If the target does not become healthy within the retry limit.
 */
export async function waitForTarget(target: TargetDefinition): Promise<void> {
  const url = target.healthEndpoint ?? target.url
  const maxRetries = target.maxRetries ?? 30
  const retryDelay = target.retryDelayMs ?? 2000

  for (let i = 1; i <= maxRetries; i++) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(5000) })
      if (response.ok) {
        return
      }
      console.error(`[e2e] ${target.name} returned ${response.status} (attempt ${i}/${maxRetries})`)
    } catch {
      console.error(`[e2e] ${target.name} not ready yet (attempt ${i}/${maxRetries})`)
    }
    await sleep(retryDelay)
  }

  throw new Error(
    `${target.name} did not become healthy after ${maxRetries} retries (${(maxRetries * retryDelay) / 1000}s) at ${url}`,
  )
}

/**
 * Start targets, wait for them, and return a cleanup function.
 * Useful for `beforeAll`/`afterAll` in tests.
 *
 * Usage:
 *   const cleanup = await setupTargets()
 *   // ... run tests ...
 *   await cleanup()
 */
export async function setupTargets(targets?: TargetDefinition[]): Promise<() => Promise<void>> {
  const t = targets ?? [JUICE_SHOP, DVWA]
  await startTargets(t.map((x) => x.name))
  await Promise.all(t.map(waitForTarget))
  return () => stopTargets(t.map((x) => x.name))
}

// ── Internal helpers ─────────────────────────────────────────────────────────

function projectRoot(): string {
  // Walk up from this file's directory to find the repo root (where docker-compose.yml lives)
  // This file is at: packages/opencode/test/argus/e2e/docker-helpers.ts
  // The repo root is: ../../../../../
  return new URL("../../../../../../", import.meta.url).pathname
}

interface RunOptions {
  cwd?: string
  description?: string
  timeoutMs?: number
}

async function runCommand(cmd: string, args: string[], opts: RunOptions = {}): Promise<{ stdout: string; stderr: string }> {
  const cwd = opts.cwd ?? process.cwd()
  const description = opts.description ?? `${cmd} ${args.join(" ")}`

  console.error(`[e2e] Running: ${description}`)

  return new Promise((resolve, reject) => {
    const proc = spawn(cmd, args, {
      cwd,
      stdio: ["ignore", "pipe", "pipe"],
      signal: opts.timeoutMs ? AbortSignal.timeout(opts.timeoutMs) : undefined,
    })

    let stdout = ""
    let stderr = ""
    proc.stdout.on("data", (chunk) => {
      stdout += chunk.toString()
    })
    proc.stderr.on("data", (chunk) => {
      stderr += chunk.toString()
    })

    proc.on("close", (code) => {
      if (code === 0) {
        resolve({ stdout, stderr })
      } else {
        reject(
          new Error(
            `${description} failed (exit ${code}):\n  stdout: ${stdout.slice(0, 500)}\n  stderr: ${stderr.slice(0, 500)}`,
          ),
        )
      }
    })
    proc.on("error", (err) => reject(new Error(`${description} spawn error: ${err.message}`)))
  })
}
