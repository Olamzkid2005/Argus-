import { Prompt, type PromptRef } from "@tui/component/prompt"
import { createEffect, createMemo, createSignal, onMount, For, Show } from "solid-js"
import { Logo } from "../component/logo"
import { useSync } from "../context/sync"
import { Toast } from "../ui/toast"
import { useArgs } from "../context/args"
import { useRouteData } from "@tui/context/route"
import { usePromptRef } from "../context/prompt"
import { useLocal } from "../context/local"
import { TuiPluginRuntime } from "@/cli/cmd/tui/plugin/runtime"
import { useEditorContext } from "@tui/context/editor"
import { useTerminalDimensions } from "@opentui/solid"
import { useTuiConfig } from "../context/tui-config"
import { useTheme, tint } from "@tui/context/theme"
import { logo as argusLogo } from "@/argus/logo"

let once = false
const placeholder = {
  normal: [
    "/assess https://example.com",
    "/recon https://testphp.vulnweb.com",
    "/doctor — run health checks",
    "/status — system status",
  ],
  shell: ["argus doctor", "argus status", "argus --help"],
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
  } catch {
    return iso
  }
}

export function Home() {
  const sync = useSync()
  const route = useRouteData("home")
  const promptRef = usePromptRef()
  const [ref, setRef] = createSignal<PromptRef | undefined>()
  const args = useArgs()
  const local = useLocal()
  const editor = useEditorContext()
  const dimensions = useTerminalDimensions()
  const tuiConfig = useTuiConfig()
  const { theme } = useTheme()
  const promptMaxWidth = createMemo(() => {
    const configured = tuiConfig.prompt?.max_width
    if (configured === "auto") return Math.max(75, Math.floor(dimensions().width * 0.7))
    return configured ?? 75
  })

  // Load recent engagements
  const [engagements, setEngagements] = createSignal<Array<{ id: string; target: string; status: string; created_at: string; findings?: number }>>([])
  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const all = store.listEngagements()
      const recent = all.slice(-5).reverse()
      const withFindings = recent.map((e) => {
        let findings = 0
        try { findings = store.getFindings(e.id).length } catch {}
        return { id: e.id, target: e.target, status: e.status, created_at: e.created_at, findings }
      })
      setEngagements(withFindings)
    } catch {
      // Engagement store not available
    }
  })

  let sent = false

  onMount(() => {
    editor.clearSelection()
  })

  const bind = (r: PromptRef | undefined) => {
    setRef(r)
    promptRef.set(r)
    if (once || !r) return
    if (route.prompt) {
      r.set(route.prompt)
      once = true
      return
    }
    if (!args.prompt) return
    r.set({ input: args.prompt, parts: [] })
    once = true
  }

  // Wait for sync and model store to be ready before auto-submitting --prompt
  createEffect(() => {
    const r = ref()
    if (sent) return
    if (!r) return
    if (!sync.ready || !local.model.ready) return
    if (!args.prompt) return
    if (r.current.input !== args.prompt) return
    sent = true
    r.submit()
  })

  const dimColor = tint(theme.background, theme.textMuted, 0.5)

  return (
    <>
      <box flexGrow={1} alignItems="center" paddingLeft={2} paddingRight={2}>
        <box flexGrow={1} minHeight={0} />
        <box height={4} minHeight={0} flexShrink={1} />
        <box flexShrink={0}>
          <TuiPluginRuntime.Slot name="home_logo" mode="replace">
            <Logo shape={argusLogo} idle />
          </TuiPluginRuntime.Slot>
        </box>
        <box height={1} minHeight={0} flexShrink={1} />
        <box width="100%" maxWidth={promptMaxWidth()} zIndex={1000} paddingTop={1} flexShrink={0}>
          <TuiPluginRuntime.Slot name="home_prompt" mode="replace" ref={bind}>
            <Prompt ref={bind} right={<TuiPluginRuntime.Slot name="home_prompt_right" />} placeholders={placeholder} />
          </TuiPluginRuntime.Slot>
        </box>
        <box height={1} minHeight={0} flexShrink={1} />
        <Show when={engagements().length > 0}>
          <box flexDirection="column" width="100%" maxWidth={promptMaxWidth()} paddingLeft={1}>
            <text fg={theme.textMuted} attributes={{ bold: true }}>Recent Engagements</text>
            <box height={1} />
            <For each={engagements()}>
              {(eng) => (
                <box flexDirection="row" gap={1}>
                  <text fg={theme.textMuted}>•</text>
                  <text fg={theme.text}>{eng.target}</text>
                  <text fg={dimColor}>
                    {eng.status.toLowerCase()} — {eng.findings ?? 0} finding(s) — {formatDate(eng.created_at)}
                  </text>
                </box>
              )}
            </For>
          </box>
        </Show>
        <TuiPluginRuntime.Slot name="home_bottom" />
        <box flexGrow={1} minHeight={0} />
        <Toast />
      </box>
      <box width="100%" flexShrink={0}>
        <TuiPluginRuntime.Slot name="home_footer" mode="single_winner" />
      </box>
    </>
  )
}
