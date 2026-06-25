/**
 * Argus TUI Command Registry
 * Registers Argus slash commands in the OpenCode keymap/command palette.
 */
import { useBindings, useKeymap } from "@opentui/keymap/solid"
import { getArgusTuiCommands } from "./tui-commands"
import { usePromptRef } from "@tui/context/prompt"
import { onMount } from "solid-js"

export function ArgusCommandRegistry() {
  // Self-guard: only register Argus commands when running in Argus mode.
  // This prevents Argus-specific slash commands from bleeding into the
  // global OpenCode TUI regardless of where this component is rendered.
  if (process.env.ARGUS_MODE !== "1") return null

  const promptRef = usePromptRef()
  const keymap = useKeymap()

  // Register each slash alias as a separate command entry so that typing /scan
  // inserts "/scan " (not "/assess "). Previously slashes[0] was always used,
  // funneling users who memorized "/scan" to "/assess".
  const argusCommands = getArgusTuiCommands().flatMap((cmd) => {
    const needsTarget = cmd.name === "assess" || cmd.name === "recon" || cmd.name === "report" || cmd.name === "verify" || cmd.name === "open"
    return cmd.slashes.map((slash) => ({
      namespace: "palette" as const,
      title: cmd.title,
      name: `argus.${cmd.name}.${slash}`,
      category: "Argus",
      desc: cmd.description,
      slashName: slash,
      slashAliases: [] as string[],
      hidden: false,
      run: () => {
        const ref = promptRef.current
        if (ref) ref.set({ input: "/" + slash + (needsTarget ? " " : ""), parts: [] })
      },
    }))
  })

  // Register commands via useBindings (same mechanism as built-in commands)
  useBindings(() => ({ commands: argusCommands }))

  // Also register directly on the keymap as a fallback
  onMount(() => {
    for (const cmd of argusCommands) {
      ;(keymap as any).registerCommand?.(cmd)
    }
  })

  return null
}
