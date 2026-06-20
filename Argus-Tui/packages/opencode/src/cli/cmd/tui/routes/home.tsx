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
  normal: ["/assess https://example.com", "/recon https://testphp.vulnweb.com", "/doctor - run health checks"],
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

  const [engagements, setEngagements] = createSignal<Array<{ id: string; target: string; status: string; findings: number }>>([])
  const [stats, setStats] = createSignal<{ targets: number; active: number; findings: number; critical: number; high: number; medium: number } | null>(null)
  const [services, setServices] = createSignal<Record<string, boolean>>({})

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const all = store.listEngagements()
      const recent = all.slice(-5).reverse()
      const enriched = recent.map((e: any) => {
        const findings = store.getFindings(e.id)
        return { id: e.id, target: e.target, status: e.status, findings: findings.length }
      })
      setEngagements(enriched as any)
      const totalTargets = new Set(all.map((e: any) => e.target)).size
      const openEngagements = all.filter((e: any) => e.status === "RUNNING" || e.status === "CREATED").length
      let critical = 0; let high = 0; let medium = 0; let totalF = 0
      for (const e of all.slice(0, 20)) {
        const findings = store.getFindings(e.id)
        totalF += findings.length
        for (const f of findings) {
          if (f.severity >= 4) critical++
          else if (f.severity === 3) high++
          else if (f.severity === 2) medium++
        }
      }
      setStats({ targets: totalTargets, active: openEngagements, findings: totalF, critical, high, medium })
    } catch {}
    Promise.resolve().then(async () => {
      try {
        const { existsSync } = await import("fs")
        const { join, dirname } = await import("path")
        const { fileURLToPath } = await import("url")
        const _dirname = dirname(fileURLToPath(import.meta.url))
        const wp = join(_dirname, "../../../../../../../../argus-workers/mcp_server.py")
        const mcpOk = existsSync(wp)
        setServices({ planner: true, workflow: true, mcp: mcpOk, evidence: true, report: true, verify: true })
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

  const sevColor = (s: number) =>
    s >= 4 ? theme.error : s === 3 ? theme.warning : s >= 1 ? theme.info : theme.success

  const statusIcon = (s: string) =>
    s === "COMPLETED" ? "\u2713" : s === "RUNNING" ? "\u27F3" : s === "FAILED" ? "\u2717" : "\u25CB"

  const statusColor = (s: string) =>
    s === "COMPLETED" ? theme.success : s === "RUNNING" ? theme.primary : s === "FAILED" ? theme.error : theme.textMuted

  const sec = (name: string) => services()[name]

  return (
    <>
      <box flexGrow={1} flexDirection="column" paddingLeft={2} paddingRight={2}>
        {/* Logo */}
        <box alignItems="center" paddingTop={2}>
          <Logo shape={argusLogo} idle />
        </box>
        <box alignItems="center" paddingTop={1}>
          <text fg={theme.text}>Autonomous Security Assessment Platform</text>
        </box>
        <box alignItems="center">
          <text fg={theme.success}>● Operational</text>
        </box>

        <box height={1} />

        {/* Stats bar */}
        <Show when={stats()}>
          <box flexDirection="row" gap={2} paddingTop={1} paddingBottom={1}>
            <box flexDirection="column" alignItems="center" minWidth={8}>
              <text fg={theme.text}><b>{stats()!.targets.toString()}</b></text>
              <text fg={theme.textMuted}>targets</text>
            </box>
            <text fg={theme.textMuted}>|</text>
            <box flexDirection="column" alignItems="center" minWidth={8}>
              <text fg={theme.warning}><b>{stats()!.active.toString()}</b></text>
              <text fg={theme.textMuted}>active</text>
            </box>
            <text fg={theme.textMuted}>|</text>
            <box flexDirection="column" alignItems="center" minWidth={10}>
              <text fg={theme.error}><b>{stats()!.findings.toString()}</b></text>
              <text fg={theme.textMuted}>findings</text>
            </box>
            <text fg={theme.textMuted}>|</text>
            <box flexDirection="column" alignItems="center" minWidth={8}>
              <text fg={theme.error}><b>{stats()!.critical.toString()}</b></text>
              <text fg={theme.textMuted}>critical</text>
            </box>
            <box flexDirection="column" alignItems="center" minWidth={6}>
              <text fg={sevColor(3)}><b>{stats()!.high.toString()}</b></text>
              <text fg={theme.textMuted}>high</text>
            </box>
            <box flexDirection="column" alignItems="center" minWidth={8}>
              <text fg={sevColor(2)}><b>{stats()!.medium.toString()}</b></text>
              <text fg={theme.textMuted}>medium</text>
            </box>
          </box>
        </Show>

        <text fg={theme.textMuted}>Quick Actions</text>
        <box flexDirection="row" gap={1} paddingTop={1}>
          <text fg={theme.primary}>/assess {"<target>"}</text>
          <text fg={theme.textMuted}>|</text>
          <text fg={theme.primary}>/recon {"<target>"}</text>
          <text fg={theme.textMuted}>|</text>
          <text fg={theme.warning}>/report {"<id>"}</text>
          <text fg={theme.textMuted}>|</text>
          <text fg={theme.info}>/verify {"<finding>"}</text>
          <text fg={theme.textMuted}>|</text>
          <text fg={theme.textMuted}>/status</text>
          <text fg={theme.textMuted}>|</text>
          <text fg={theme.error}>/doctor</text>
        </box>

        <box height={1} />

        {/* Recent engagements */}
        <text fg={theme.textMuted}>Recent Activity</text>
        <Show when={engagements().length > 0}
          fallback={<text fg={theme.textMuted}>No engagements yet. Run /assess to get started.</text>}
        >
          <For each={engagements()}>
            {(eng) => (
              <box flexDirection="row" gap={1} paddingTop={1}>
                <text fg={statusColor(eng.status)}>{statusIcon(eng.status)}</text>
                <text fg={theme.textMuted}>{eng.id}</text>
                <text fg={theme.text}>{eng.target}</text>
                <text fg={statusColor(eng.status)}>{eng.status.toLowerCase()}</text>
                <text fg={theme.textMuted}>({eng.findings} findings)</text>
              </box>
            )}
          </For>
        </Show>

        <box height={1} />

        {/* System Health */}
        <text fg={theme.textMuted}>System Status</text>
        <box flexDirection="row" gap={2} paddingTop={1}>
          <For each={[
            { label: "Planner", key: "planner" },
            { label: "Workflow", key: "workflow" },
            { label: "MCP Bridge", key: "mcp" },
            { label: "Evidence Store", key: "evidence" },
            { label: "Report Gen", key: "report" },
            { label: "Browser Verify", key: "verify" },
          ]}>
            {(svc) => (
              <box flexDirection="row" gap={1}>
                <text fg={sec(svc.key) ? theme.success : theme.error}>●</text>
                <text fg={sec(svc.key) ? theme.text : theme.textMuted}>{svc.label}</text>
              </box>
            )}
          </For>
        </box>

        <box paddingTop={2} width="100%" maxWidth={promptMaxWidth()}>
          <TuiPluginRuntime.Slot name="home_prompt" mode="replace" ref={bind}>
            <Prompt ref={bind} right={<TuiPluginRuntime.Slot name="home_prompt_right" />} placeholders={placeholder} />
          </TuiPluginRuntime.Slot>
        </box>
        <box flexGrow={1} minHeight={0} />
        <Toast />
      </box>
      <box width="100%" flexShrink={0} paddingLeft={2} paddingRight={2} paddingTop={1} paddingBottom={1} justifyContent="space-between" flexDirection="row">
        <text fg={theme.primary}>ARGUS v5</text>
        <text fg={theme.textMuted}>Security Assessment Platform</text>
        <TuiPluginRuntime.Slot name="home_footer" mode="single_winner" />
      </box>
    </>
  )
}
