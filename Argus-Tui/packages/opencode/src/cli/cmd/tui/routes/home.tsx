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
import { useTheme } from "@tui/context/theme"
import { logo as argusLogo } from "@/argus/logo"

let once = false
const placeholder = {
  normal: ["/assess https://example.com", "/recon https://testphp.vulnweb.com", "/doctor — run health checks"],
  shell: ["argus doctor", "argus status", "argus --help"],
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
    return configured ?? 85
  })

  const [engagements, setEngagements] = createSignal<Array<{ id: string; target: string; status: string }>>([])
  const [statusLine, setStatusLine] = createSignal("")

  let doctorCache: { results: string; ts: number } | null = null

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const all = store.listEngagements() as Array<{ id: string; target: string; status: string }>
      setEngagements(all.slice(-5).reverse())
    } catch {}
    // Quick async status check without importing doctorCommand (which launches MCP)
    Promise.resolve().then(async () => {
      try {
        if (doctorCache && Date.now() - doctorCache.ts < 30000) {
          setStatusLine(doctorCache.results)
          return
        }
        const { existsSync } = await import("fs")
        const { join, dirname } = await import("path")
        const { fileURLToPath } = await import("url")
        const _dirname = dirname(fileURLToPath(import.meta.url))
        const wp = join(_dirname, "../../../../../../../argus-workers/mcp_server.py")
        const mcpOk = existsSync(wp)
        setStatusLine(mcpOk ? "All systems operational" : "Limited — MCP worker not found")
        doctorCache = { results: mcpOk ? "All systems operational" : "Limited", ts: Date.now() }
      } catch {}
    })
  })

  let sent = false
  onMount(() => { editor.clearSelection() })

  const bind = (r: PromptRef | undefined) => {
    setRef(r); promptRef.set(r)
    if (once || !r) return
    if (route.prompt) { r.set(route.prompt); once = true; return }
    if (!args.prompt) return
    r.set({ input: args.prompt, parts: [] }); once = true
  }

  createEffect(() => {
    const r = ref()
    if (sent || !r) return
    if (!sync.ready || !local.model.ready) return
    if (!args.prompt) return
    if (r.current.input !== args.prompt) return
    sent = true; r.submit()
  })

  return (
    <>
      <box flexGrow={1} flexDirection="column" paddingLeft={2} paddingRight={2}>
        <box alignItems="center" paddingTop={2}>
          <Logo shape={argusLogo} idle />
        </box>
        <box alignItems="center" paddingTop={1}>
          <text fg={theme.text}>Autonomous Security Assessment Platform</text>
        </box>
        <box alignItems="center" paddingTop={1}>
          <text fg={theme.primary}>● Ready for assessment operations.</text>
        </box>
        <box height={2} />
        <box flexDirection="row" maxWidth={promptMaxWidth()}>
          <box flexDirection="column" flexGrow={1}>
            <text fg={theme.text}>Quick Actions</text>
            <text fg={theme.primary}>/assess {'<target>'}    Run full assessment</text>
            <text fg={theme.primary}>/recon  {'<target>'}    Recon only</text>
            <text fg={theme.warning}>/report {'<id>'}        Generate report</text>
            <text fg={theme.error}>/doctor              Health diagnostics</text>
            <text fg={theme.textMuted}>/status              System status</text>
          </box>
          <box flexDirection="column" flexGrow={1}>
            <text fg={theme.text}>Recent Engagements</text>
            <Show when={engagements().length > 0}
              fallback={<text fg={theme.textMuted}>No engagements yet.</text>}
            >
              <For each={engagements()}>
                {(eng) => (
                  <box flexDirection="row" gap={1}>
                    <text fg={theme.textMuted}>{eng.target}</text>
                    <text fg={eng.status === "COMPLETED" ? theme.success : eng.status === "RUNNING" ? theme.primary : theme.textMuted}>
                      {eng.status.toLowerCase()}
                    </text>
                  </box>
                )}
              </For>
            </Show>
            <box height={1} />
            <text fg={theme.text}>System</text>
            <text fg={theme.success}>● MCP Worker</text>
            <text fg={theme.success}>● Planner</text>
            <text fg={theme.success}>● Evidence Store</text>
            <text fg={theme.textMuted}>{statusLine()}</text>
          </box>
        </box>
        <box paddingTop={2} width="100%" maxWidth={promptMaxWidth()}>
          <TuiPluginRuntime.Slot name="home_prompt" mode="replace" ref={bind}>
            <Prompt ref={bind} right={<TuiPluginRuntime.Slot name="home_prompt_right" />} placeholders={placeholder} />
          </TuiPluginRuntime.Slot>
        </box>
        <box flexGrow={1} minHeight={0} />
        <Toast />
      </box>
      <box width="100%" flexShrink={0}>
        <TuiPluginRuntime.Slot name="home_footer" mode="single_winner" />
      </box>
    </>
  )
}
