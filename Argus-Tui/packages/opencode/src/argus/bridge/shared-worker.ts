/**
 * Process-wide MCP worker cache for TUI slash commands.
 *
 * `/doctor`, `/status`, and `/tools` all need the Python MCP worker. Each used
 * to spawn its own copy and shut it down afterwards, paying the worker's full
 * startup cost (interpreter + tool imports + version probes) on every command.
 * Keep one healthy worker per worker/python pair instead, and hand it to each
 * command. The worker is only killed when it fails a health check or the
 * process exits.
 *
 * CLI commands deliberately do not use this cache: they are one-shot, and a
 * cached child process would keep `argus doctor` alive after it finishes.
 */

import { WorkersBridge, resolveDefaultPython } from "./mcp-client"
import { MCP_WORKER_PATH } from "../shared/path"

interface CacheEntry {
  bridge: WorkersBridge
  ready: Promise<WorkersBridge>
}

const cache = new Map<string, CacheEntry>()
let exitHookInstalled = false

function keyFor(workersPath: string, pythonPath: string): string {
  return `${pythonPath}\0${workersPath}`
}

function installExitHook(): void {
  if (exitHookInstalled) return
  exitHookInstalled = true
  // `exit` handlers cannot await, but signalling the child is synchronous.
  // Without this, closing the TUI would orphan the Python worker (and its
  // subprocesses) on platforms where the child is not tied to the parent.
  process.once("exit", () => {
    for (const entry of cache.values()) {
      try {
        entry.bridge.killChild()
      } catch {
        // best effort — the process is going away
      }
    }
  })
}

/**
 * Return a connected, healthy worker for the given paths, spawning one only
 * when no live worker is cached. Concurrent callers share one spawn.
 */
export async function acquireSharedWorker(options?: {
  workersPath?: string
  pythonPath?: string
}): Promise<WorkersBridge> {
  const workersPath = options?.workersPath ?? MCP_WORKER_PATH
  const pythonPath = options?.pythonPath ?? resolveDefaultPython()
  const key = keyFor(workersPath, pythonPath)

  const existing = cache.get(key)
  if (existing) {
    try {
      await existing.ready
      if (await existing.bridge.isHealthy(5000)) return existing.bridge
    } catch {
      // Fall through and replace the dead entry.
    }
    if (cache.get(key) === existing) cache.delete(key)
    await existing.bridge.disconnect().catch(() => {})
  }

  const bridge = new WorkersBridge(workersPath, pythonPath)
  const entry: CacheEntry = {
    bridge,
    ready: bridge.connect().then(() => bridge),
  }
  cache.set(key, entry)
  installExitHook()

  try {
    return await entry.ready
  } catch (error) {
    if (cache.get(key) === entry) cache.delete(key)
    await bridge.disconnect().catch(() => {})
    throw error
  }
}

/** Whether a connected worker is cached for these paths (no health probe). */
export function hasSharedWorker(options?: { workersPath?: string; pythonPath?: string }): boolean {
  const workersPath = options?.workersPath ?? MCP_WORKER_PATH
  const pythonPath = options?.pythonPath ?? resolveDefaultPython()
  return cache.has(keyFor(workersPath, pythonPath))
}

/** Shut down every cached worker. Used by tests and process teardown. */
export async function disposeSharedWorkers(): Promise<void> {
  const entries = [...cache.values()]
  cache.clear()
  await Promise.all(entries.map((entry) => entry.bridge.disconnect().catch(() => {})))
}
