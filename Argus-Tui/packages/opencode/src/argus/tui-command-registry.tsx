/**
 * Argus TUI Command Registry
 *
 * Registers Argus slash commands in the OpenCode keymap/command palette
 * so they appear in autocomplete, /help, and the command palette.
 *
 * Import <ArgusCommandRegistry /> anywhere inside the TUI component tree.
 */

import { useBindings } from "@opentui/keymap/solid"
import { getArgusTuiCommands } from "./tui-commands"

export function ArgusCommandRegistry() {
  const argusCommands = getArgusTuiCommands().map((cmd) => ({
    title: cmd.title,
    name: `argus.${cmd.name}`,
    category: "Argus",
    desc: cmd.description,
    slashName: cmd.name,
    slashAliases: cmd.slashes.filter((s) => s !== cmd.name),
    hidden: false,
    run: () => {
      // The actual execution is handled by the prompt component's
      // Argus routing logic. This registration makes the command
      // visible in the palette and autocomplete.
    },
  }))

  useBindings(() => ({
    commands: argusCommands,
  }))

  return null
}
