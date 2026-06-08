/**
 * Argus TUI Command Registry
 * Registers Argus slash commands in the OpenCode keymap/command palette.
 */
import { useBindings, useKeymap } from "@opentui/keymap/solid"
import { getArgusTuiCommands } from "./tui-commands"
import { usePromptRef } from "@tui/context/prompt"
import { onMount } from "solid-js"

export function ArgusCommandRegistry() {
  const promptRef = usePromptRef()
  const keymap = useKeymap()

  const argusCommands = getArgusTuiCommands().map((cmd) => {
    const needsTarget = cmd.name === "assess" || cmd.name === "recon" || cmd.name === "report" || cmd.name === "verify" || cmd.name === "open"
    const insertText = `/${cmd.slashes[0]}${needsTarget ? " " : ""}`
    return {
      namespace: "palette" as const,
      title: cmd.title,
      name: `argus.${cmd.name}`,
      category: "Argus",
      desc: cmd.description,
      slashName: cmd.name,
      slashAliases: cmd.slashes.filter((s) => s !== cmd.name),
      hidden: false,
      run: () => {
        const ref = promptRef.current
        if (ref) ref.set({ input: insertText, parts: [] })
      },
    }
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
