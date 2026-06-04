/**
 * Argus TUI Command Registry
 * Registers Argus slash commands in the OpenCode keymap/command palette.
 */
import { useBindings } from "@opentui/keymap/solid"
import { getArgusTuiCommands } from "./tui-commands"
import { usePromptRef } from "@tui/context/prompt"

export function ArgusCommandRegistry() {
  const promptRef = usePromptRef()
  const argusCommands = getArgusTuiCommands().map((cmd) => {
    const needsTarget = cmd.name === "assess" || cmd.name === "recon" || cmd.name === "report" || cmd.name === "verify"
    const insertText = `/${cmd.slashes[0]}${needsTarget ? " " : ""}`
    return {
      title: cmd.title, name: `argus.${cmd.name}`, category: "Argus",
      desc: cmd.description, slashName: cmd.name,
      slashAliases: cmd.slashes.filter((s) => s !== cmd.name), hidden: false,
      run: () => {
        const ref = promptRef.current
        if (ref) ref.set({ input: insertText, parts: [] })
      },
    }
  })
  useBindings(() => ({ commands: argusCommands }))
  return null
}
