import { spawn, type SpawnOptions } from "child_process"
import { fileURLToPath } from "url"

/** Keep the terminal attached while the child owns rendering and cleanup. */
export function spawnForeground(command: string, args: string[], options: SpawnOptions) {
  const child = spawn(command, args, options)
  const forward = (signal: NodeJS.Signals) => child.kill(signal)
  const interrupt = () => forward("SIGINT")
  const terminate = () => forward("SIGTERM")
  const hangup = () => forward("SIGHUP")
  const cleanup = () => {
    process.off("SIGINT", interrupt)
    process.off("SIGTERM", terminate)
    process.off("SIGHUP", hangup)
  }
  process.on("SIGINT", interrupt)
  process.on("SIGTERM", terminate)
  process.on("SIGHUP", hangup)
  child.once("error", (error) => {
    cleanup()
    console.error(`Failed to launch ${command}: ${error.message}`)
    process.exitCode = 1
  })
  child.once("close", (code, signal) => {
    cleanup()
    if (signal) {
      process.kill(process.pid, signal)
      return
    }
    process.exitCode = code !== null && code >= 0 ? code : 1
  })
  return child
}

export function launchTui(
  args: string[] = [],
  start: (command: string, args: string[], options: SpawnOptions) => unknown = spawnForeground,
) {
  return start(
    process.execPath,
    [
      "run",
      "--conditions=browser",
      "--preload",
      fileURLToPath(import.meta.resolve("@opentui/solid/preload")),
      fileURLToPath(new URL("../index.ts", import.meta.url)),
      ...args,
    ],
    {
      stdio: "inherit",
      cwd: process.cwd(),
      // The legacy dashboard has no prompt; the branded home hosts /assess.
      env: { ...process.env, ARGUS_MODE: "1", OPENCODE_ROUTE: process.env.OPENCODE_ROUTE ?? '{"type":"home"}' },
    },
  )
}
