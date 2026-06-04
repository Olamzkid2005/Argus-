/**
 * Argus TUI Command Registry
 *
 * Registers Argus slash commands in the OpenCode keymap/command palette
 * so they appear in autocomplete, /help, and the command palette.
 *
 * When a command is selected from the palette, the run handler inserts
 * the slash command text into the prompt via the promptRef.
 *
 * Import <ArgusCommandRegistry /> anywhere inside the TUI component tree.
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
      title: cmd.title,
      name: `argus.${cmd.name}`,
      category: "Argus",
      desc: cmd.description,
      slashName: cmd.name,
      slashAliases: cmd.slashes.filter((s) => s !== cmd.name),
      hidden: false,
      run: () => {
        const ref = promptRef()
        if (ref) {
          ref.set({ input: insertText, parts: [] })
        }
      },
    }
  })

  useBindings(() => ({
    commands: argusCommands,
  }))

  return null
}
