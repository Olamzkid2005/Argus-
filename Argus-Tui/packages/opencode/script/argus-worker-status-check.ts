/**
 * Live check for the worker-tool-state channel.
 *
 * Spawns the real Python MCP worker, reads `list_tools`, feeds the result into
 * a real `ToolRegistry` loaded from the real `tool-definitions.yaml`, and
 * reports (a) which tools the worker says it cannot run and (b) whether the
 * MCP/registry drift report is clean.
 *
 * Run from packages/opencode:  bun run script/argus-worker-status-check.ts
 *
 * This is a manual verification harness, not a unit test: it needs the repo
 * virtualenv and installed scanner binaries to be meaningful.
 */
import { join } from "path"
import { WorkersBridge } from "../src/argus/bridge/mcp-client"
import { ToolRegistry } from "../src/argus/workflows/tool-registry"
import { MCP_WORKER_PATH, PROJECT_ROOT } from "../src/argus/shared/path"

async function main(): Promise<void> {
  const registry = new ToolRegistry()
  registry.load(join(PROJECT_ROOT, "Argus-Tui/packages/opencode/src/argus/workflows/tool-definitions.yaml"))
  console.log(`registry: ${registry.listTools().length} tool(s)`)

  const bridge = new WorkersBridge(MCP_WORKER_PATH)
  await bridge.connect()
  try {
    const workerTools = await bridge.getTools()
    console.log(`mcp worker: ${workerTools.length} tool(s)`)

    const blocked = registry.setWorkerToolStatus(workerTools as any)
    console.log(`\nblocked by the worker (${blocked.length}):`)
    for (const b of blocked) console.log(`  ${b.name.padEnd(32)} ${b.reason}`)

    bridge.setRegistryTools(registry.listTools() as any)
    const drift = await bridge.detectDrift()
    console.log(`\ndrift:`)
    console.log(`  missing_from_registry: ${JSON.stringify(drift.missing_from_registry)}`)
    console.log(`  missing_from_mcp:      ${JSON.stringify(drift.missing_from_mcp)}`)
    console.log(`  capability_gaps (${drift.capability_gaps.length}):`)
    for (const gap of drift.capability_gaps) console.log(`    ${gap}`)
  } finally {
    await bridge.disconnect()
  }
}

await main()
