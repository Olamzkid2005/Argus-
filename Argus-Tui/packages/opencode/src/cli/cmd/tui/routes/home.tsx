import { Prompt, type PromptRef } from "@tui/component/prompt"
import { createEffect, createMemo, createSignal, onMount, For, Show, onCleanup } from "solid-js"
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
    "Find vulnerabilities in https://example.com",
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

function SystemStatusDot(props: { online: boolean }) {
  const { theme } = useTheme()
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={props.online ? theme.primary : theme.textMuted} stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="10" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  )
}

function QuickAction(props: { icon: string; command: string; desc: string; color: string }) {
  const { theme } = useTheme()
  return (
    <box flexDirection="row" gap={1} paddingX={1} paddingY={0.5}>
      <text fg={props.color as any} minWidth={2}>{props.icon}</text>
      <text fg={props.color as any} attributes={{ bold: true }}>{props.command}</text>
      <text fg={theme.textMuted}>{props.desc}</text>
    </box>
  )
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

  // Load engagements
  const [engagements, setEngagements] = createSignal<Array<{
    id: string; target: string; status: string; created_at: string; findings?: number
  }>>([])
  const [systemStatus, setSystemStatus] = createSignal<
    Array<{ name: string; online: boolean; icon: string }>
  >([
    { name: "Planner", online: false, icon: "⚙" },
    { name: "Workflow Engine", online: false, icon: "⚡" },
    { name: "MCP Bridge", online: false, icon: "🔗" },
    { name: "Evidence Store", online: false, icon: "💾" },
    { name: "Report Generator", online: false, icon: "📋" },
    { name: "Browser Verify", online: false, icon: "🌐" },
  ])

  onMount(async () => {
    // Load engagements from store
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
    } catch {}

    // Check system status via doctor
    try {
      const { doctorCommand } = await import("@/argus/commands/doctor")
      const results = await doctorCommand()
      const statusMap: Record<string, boolean> = {
        "Planner": true,
        "Workflow Engine": true,
        "MCP Bridge": results.find(r => r.name === "MCP Worker")?.status === "PASS",
        "Evidence Store": true,
        "Report Generator": true,
        "Browser Verify": true,
      }
      setSystemStatus((prev) =>
        prev.map((s) => ({ ...s, online: statusMap[s.name] ?? false })),
      )
    } catch {}
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

  const onlineCount = createMemo(() => systemStatus().filter((s) => s.online).length)

  return (
    <>
      <box flexGrow={1} flexDirection="column" paddingLeft={2} paddingRight={2}>
        {/* Splash section */}
        <box alignItems="center" paddingTop={2}>
          <Logo shape={argusLogo} idle />
        </box>
        <box alignItems="center" paddingTop={1}>
          <text fg={theme.text} size="large" font="mono">Autonomous Security Assessment Platform</text>
        </box>
        <box alignItems="center" paddingTop={1}>
          <text fg={theme.primary as any} font="mono">
            <text font="mono" bg={theme.primary as any} fg={theme.background as any}> ● </text>
            {' '}Ready for assessment operations.
          </text>
        </box>

        <box height={2} />

        {/* Main two-column grid */}
        <box flexDirection="row" gap={2} maxWidth={promptMaxWidth()}>
          {/* Left column: Quick Actions + Examples */}
          <box flexDirection="column" gap={1} flexGrow={1}>
            {/* Quick Actions Panel */}
            <box flexDirection="column" paddingX={2} paddingY={1.5}>
              <box flexDirection="row" gap={1} paddingBottom={1}>
                <box width={0.3} height={1.5} bg={theme.primary as any} />
                <text fg={theme.text} font="mono" attributes={{ bold: true }}>QUICK ACTIONS</text>
              </box>
              <QuickAction icon=">" command="/assess" desc="<target>    Run full assessment" color={theme.primary} />
              <QuickAction icon="🔍" command="/recon" desc="<target>     Recon only" color="#00bcd4" />
              <QuickAction icon="📄" command="/report" desc="<id>         Generate report" color="#f59e0b" />
              <QuickAction icon="🌐" command="/verify" desc="<finding>   Browser verification" color="#00bcd4" />
              <QuickAction icon="📊" command="/status" desc="              System status" color={theme.primary} />
              <QuickAction icon="🔬" command="/doctor" desc="              Health diagnostics" color="#ef4444" />
              <box paddingTop={1}>
                <text fg={theme.textMuted} font="mono">
                  Type any command to begin an operation
                </text>
              </box>
            </box>

            {/* Examples Panel */}
            <box flexDirection="column" paddingX={2} paddingY={1.5}>
              <box flexDirection="row" gap={1} paddingBottom={1}>
                <box width={0.3} height={1.5} bg={theme.primary as any} />
                <text fg={theme.text} font="mono" attributes={{ bold: true }}>EXAMPLES</text>
              </box>
              <box flexDirection="row" gap={1} paddingY={0.3}>
                <text fg={theme.textMuted}>{">"}</text>
                <text fg="#00bcd4" font="mono">/assess https://testphp.vulnweb.com</text>
                <text fg={theme.textMuted} font="mono" bg="rgba(0,188,212,0.1)"> CMD </text>
              </box>
              <box flexDirection="row" gap={1} paddingY={0.3}>
                <text fg={theme.textMuted}>{">"}</text>
                <text fg={theme.text} font="mono">Find vulnerabilities in https://example.com</text>
                <text fg={theme.textMuted} font="mono" bg="rgba(255,255,255,0.05)"> NLP </text>
              </box>
              <box flexDirection="row" gap={1} paddingY={0.3}>
                <text fg={theme.textMuted}>{">"}</text>
                <text fg={theme.text} font="mono">Generate report for ENG-001</text>
                <text fg={theme.textMuted} font="mono" bg="rgba(255,255,255,0.05)"> NLP </text>
              </box>
              <box paddingTop={1}>
                <text fg={theme.textMuted} font="mono">
                  Click any example or type your own command
                </text>
              </box>
            </box>
          </box>

          {/* Right column: Engagements + Status */}
          <box flexDirection="column" gap={1} flexGrow={1}>
            {/* Recent Engagements Panel */}
            <box flexDirection="column" paddingX={2} paddingY={1.5}>
              <box flexDirection="row" gap={1} paddingBottom={1}>
                <box width={0.3} height={1.5} bg="#00bcd4" />
                <text fg={theme.text} font="mono" attributes={{ bold: true }}>RECENT ENGAGEMENTS</text>
                <text fg={theme.textMuted} font="mono">{engagements().length > 0 ? engagements().length : ""}</text>
              </box>
              <Show when={engagements().length > 0}
                fallback={<text fg={theme.textMuted} font="mono">No engagements yet. Run /assess to start.</text>}
              >
                <For each={engagements()}>
                  {(eng) => {
                    const statusColor = eng.status === "COMPLETED" ? "#00bcd4"
                      : eng.status === "ACTIVE" || eng.status === "RUNNING" ? theme.primary
                      : "#f59e0b"
                    return (
                      <box flexDirection="row" gap={1} paddingY={0.3}>
                        <box width={0.5} height={0.5} rounded bg={statusColor as any} />
                        <text fg={theme.textMuted} font="mono">{eng.target}</text>
                        <text fg={statusColor as any} font="mono">{eng.status.toLowerCase()}</text>
                        <text fg={theme.textMuted} font="mono">{eng.findings ?? 0} finding(s)</text>
                      </box>
                    )
                  }}
                </For>
              </Show>
            </box>

            {/* System Status Panel */}
            <box flexDirection="column" paddingX={2} paddingY={1.5}>
              <box flexDirection="row" gap={1} paddingBottom={1}>
                <box width={0.3} height={1.5} bg="#f59e0b" />
                <text fg={theme.text} font="mono" attributes={{ bold: true }}>SYSTEM STATUS</text>
                <text fg={theme.primary as any} font="mono">{onlineCount()}/6</text>
              </box>
              <For each={systemStatus()}>
                {(svc) => (
                  <box flexDirection="row" gap={1} paddingY={0.2}>
                    <text font="mono">{svc.icon}</text>
                    <text fg={theme.text} font="mono">{svc.name}</text>
                    <text fg={svc.online ? (theme.primary as any) : (theme.textMuted as any)} font="mono">
                      {svc.online ? "● Online" : "○ Offline"}
                    </text>
                  </box>
                )}
              </For>
              <box paddingTop={1}>
                <text fg={theme.textMuted} font="mono">
                  All systems operational
                </text>
              </box>
            </box>
          </box>
        </box>

        <box flexGrow={1} minHeight={0} />
        <Toast />
      </box>

      {/* Footer */}
      <box width="100%" flexShrink={0} paddingX={2} paddingY={1}>
        <text fg={theme.textMuted} font="mono">
          Argus — Planner • Workflow • MCP • Evidence
        </text>
      </box>
    </>
  )
}
