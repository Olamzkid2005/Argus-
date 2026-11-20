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
      // Selecting this from the autocomplete keeps whatever the user typed
      // (or pasted) so run() below can execute an exact command instead of
      // seeing a prompt the autocomplete already emptied.
      keepPromptText: true,
      run: () => {
        const ref = promptRef.current
        if (!ref) return

        // This entry is what Enter on the autocomplete menu and the command
        // palette execute. When the prompt already holds this command (typed
        // or pasted), run it. Previously the command's own text was written
        // back into the prompt instead, so "/config" + Enter looked like the
        // UI pasting its own words and nothing was queried.
        const current = ref.current.input.trim().toLowerCase()
        const typed = ["/" + slash, ...cmd.slashes.map((alias) => "/" + alias)].some(
          (name) => current === name.toLowerCase() || current.startsWith(name.toLowerCase() + " "),
        )
        const missingTarget = needsTarget && !current.includes(" ")
        if (typed && !missingTarget) {
          ref.submit()
          return
        }

        // Otherwise just pre-fill the prompt: commands that take a target still
        // need the user to supply one.
        ref.set({ input: "/" + slash + (needsTarget ? " " : ""), parts: [] })
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
