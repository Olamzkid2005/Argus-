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

function SectionLabel(props: { children: any }) {
  const { theme } = useTheme()
  return (
    <box flexDirection="row" paddingBottom={1} marginBottom={1}>
      <text fg={theme.textMuted}>{props.children}</text>
    </box>
  )
}

function Separator() {
  const { theme } = useTheme()
  return <text fg={theme.border}>──────────────────────────────────────────────</text>
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
  const [stats, setStats] = createSignal<{ targets: number; active: number; critical: number; high: number; medium: number; total: number } | null>(null)
  const [services, setServices] = createSignal<Record<string, boolean>>({})

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const all = store.listEngagements()
      setEngagements(all.slice(-5).reverse() as Array<{ id: string; target: string; status: string }>)
      const totalTargets = new Set(all.map((e: any) => e.target)).size
      const openEngagements = all.filter((e: any) => e.status === "RUNNING" || e.status === "CREATED").length
      let critical = 0; let high = 0; let medium = 0; let total = 0
      for (const e of all.slice(0, 20)) {
        const findings = store.getFindings(e.id)
        total += findings.length
        for (const f of findings) {
          const sev = String(f.severity ?? "").toUpperCase()
          if (sev === "CRITICAL") critical++
          else if (sev === "HIGH") high++
          else if (sev === "MEDIUM") medium++
        }
      }
      setStats({ targets: totalTargets, active: openEngagements, critical, high, medium, total })
    } catch {}
    Promise.resolve().then(async () => {
      try {
        const { existsSync } = await import("fs")
        const { join, dirname } = await import("path")
        const { fileURLToPath } = await import("url")
        const _dirname = dirname(fileURLToPath(import.meta.url))
        const wp = join(_dirname, "../../../../../../../argus-workers/mcp_server.py")
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

  const sec = (name: string) => services()[name]

  return (
    <>
      <box flexGrow={1} flexDirection="column" paddingLeft={2} paddingRight={2}>
        {/* Splash Banner */}
        <box alignItems="center" paddingTop={2}>
          <Logo shape={argusLogo} idle />
        </box>
        <box alignItems="center" paddingTop={1}>
          <text fg={theme.text}>Autonomous Security Assessment Platform</text>
        </box>
        <box alignItems="center" paddingTop={1}>
          <text fg={theme.primary}>● Ready for assessment operations</text>
        </box>

        {/* Summary Stats */}
        <Show when={stats()}>
          <box flexDirection="row" gap={3} paddingTop={1} paddingBottom={1}>
            <box flexDirection="column" alignItems="center">
              <text fg={theme.text}><b>{stats()!.targets.toString()}</b></text>
              <text fg={theme.textMuted}>targets</text>
            </box>
            <box flexDirection="column" alignItems="center">
              <text fg={theme.warning}><b>{stats()!.active.toString()}</b></text>
              <text fg={theme.textMuted}>active</text>
            </box>
            <box flexDirection="column" alignItems="center">
              <text fg={theme.error}><b>{stats()!.critical.toString()}</b></text>
              <text fg={theme.textMuted}>critical</text>
            </box>
            <box flexDirection="column" alignItems="center">
              <text fg={theme.error}><b>{stats()!.high.toString()}</b></text>
              <text fg={theme.textMuted}>high</text>
            </box>
            <box flexDirection="column" alignItems="center">
              <text fg={theme.warning}><b>{stats()!.medium.toString()}</b></text>
              <text fg={theme.textMuted}>medium</text>
            </box>
            <box flexDirection="column" alignItems="center">
              <text fg={theme.primary}><b>{stats()!.total.toString()}</b></text>
              <text fg={theme.textMuted}>total</text>
            </box>
          </box>
        </Show>

        <Separator />

        {/* Two-column: Quick Actions | Recent Engagements */}
        <box flexDirection="row" maxWidth={promptMaxWidth()} paddingTop={1}>
          {/* Quick Actions */}
          <box flexDirection="column" flexGrow={1} paddingRight={1}>
            <SectionLabel>Quick Actions</SectionLabel>
            <box flexDirection="column" gap={0}>
              <text fg={theme.primary}>/assess {'<target>'}    Run full assessment</text>
              <text fg={theme.primary}>/recon  {'<target>'}    Recon only</text>
              <text fg={theme.primary}>/report {'<id>'}        Generate report</text>
              <text fg={theme.info}>/verify {'<finding>'}    Browser verification</text>
              <text fg={theme.textMuted}>/status              System status</text>
              <text fg={theme.error}>/doctor              Health diagnostics</text>
            </box>
          </box>

          {/* Recent Engagements */}
          <box flexDirection="column" flexGrow={1} paddingLeft={1}>
            <SectionLabel>Recent Engagements</SectionLabel>
            <Show when={engagements().length > 0}
              fallback={
                <box flexDirection="column" gap={0}>
                  <text fg={theme.textMuted}>No engagements found. Run:</text>
                  <text fg={theme.primary}>/assess https://target.com</text>
                </box>
              }
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
          </box>
        </box>

        {/* System Status */}
        <box paddingTop={1}>
          <SectionLabel>System Status</SectionLabel>
          <box flexDirection="row" gap={2}>
            <For each={[
              { label: "Planner", key: "planner" },
              { label: "Workflow Engine", key: "workflow" },
              { label: "MCP Bridge", key: "mcp" },
            ]}>
              {(svc) => (
                <box flexDirection="row" gap={1}>
                  <text fg={sec(svc.key) ? theme.success : theme.error}>●</text>
                  <text fg={sec(svc.key) ? theme.text : theme.textMuted}>{svc.label}</text>
                </box>
              )}
            </For>
          </box>
          <box flexDirection="row" gap={2}>
            <For each={[
              { label: "Evidence Store", key: "evidence" },
              { label: "Report Generator", key: "report" },
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
        </box>

        {/* Example Prompts */}
        <box paddingTop={1}>
          <SectionLabel>Examples</SectionLabel>
          <box flexDirection="row" gap={2}>
            <text fg={theme.textMuted}>/assess https://testphp.vulnweb.com</text>
          </box>
          <box flexDirection="row" gap={2}>
            <text fg={theme.textMuted}>/recon https://example.com</text>
          </box>
          <box flexDirection="row" gap={2}>
            <text fg={theme.textMuted}>Find vulnerabilities in https://example.com</text>
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
      {/* Footer with version */}
      <box width="100%" flexShrink={0} paddingX={2} paddingY={1} justifyContent="space-between" flexDirection="row">
        <text fg={theme.textMuted}>ARGUS v5</text>
        <TuiPluginRuntime.Slot name="home_footer" mode="single_winner" />
      </box>
    </>
  )
}
