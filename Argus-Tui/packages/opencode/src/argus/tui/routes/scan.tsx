/**
 * Scan Dashboard — Real-time assessment progress and results.
 */
import { createMemo, createSignal, onMount, For, Show, onCleanup } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { Toast } from "@tui/ui/toast"
import { useRouteData } from "@tui/context/route"

interface EngPhase { id: string; name: string; status: string; error?: string }
interface EngFinding { title: string; severity: number; confidence: number; tool: string; description?: string }
interface EngagementData {
  id: string; target: string; status: string
  phases: Array<{ name: string; status: string; errors: string[] }>
  findings: EngFinding[]
}

export function ScanDashboard() {
  const route = useRouteData("scan")
  const { theme } = useTheme()
  const [data, setData] = createSignal<EngagementData | null>(null)
  const [loading, setLoading] = createSignal(true)
  const [error, setError] = createSignal<string | null>(null)

  const loadData = async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const engagement = store.getEngagement(route.engagementId)
      if (!engagement) { setError("Engagement not found"); setLoading(false); return }
      const engPhases = store.getPhases(route.engagementId) as EngPhase[]
      const engFindings = store.getFindings(route.engagementId) as EngFinding[]
      setData({
        id: engagement.id, target: engagement.target, status: engagement.status,
        phases: engPhases.map((p: EngPhase) => ({ name: p.name || p.id, status: p.status, errors: p.error ? [p.error] : [] })),
        findings: engFindings.map((f: EngFinding) => ({ title: f.title, severity: f.severity ?? 0, confidence: f.confidence ?? 0, tool: f.tool })),
      })
      setLoading(false)
      if (engagement.status === "RUNNING") {
        let pollCount = 0
        const interval = setInterval(async () => {
          pollCount++
          try {
            const updated = store.getEngagement(route.engagementId)
            if (!updated) return
            const uPhases = store.getPhases(route.engagementId) as EngPhase[]
            const uFindings = store.getFindings(route.engagementId) as EngFinding[]
            setData((prev: EngagementData | null) => prev ? {
              ...prev, status: updated.status,
              phases: uPhases.map((p: EngPhase) => ({ name: p.name || p.id, status: p.status, errors: p.error ? [p.error] : [] })),
              findings: uFindings.map((f: EngFinding) => ({ title: f.title, severity: f.severity ?? 0, confidence: f.confidence ?? 0, tool: f.tool })),
            } : null)
            if (updated.status === "COMPLETED" || updated.status === "FAILED") clearInterval(interval)
          } catch (e) { console.error("Poll error:", e) }
        }, pollCount < 5 ? 1000 : 5000)
        onCleanup(() => clearInterval(interval))
      }
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); setLoading(false) }
  }
  onMount(loadData)

  const severityColor = (s: number) => s >= 4 ? theme.error : s >= 3 ? theme.warning : s >= 2 ? theme.primary : theme.textMuted
  const statusColor = (s: string) => s === "COMPLETED" || s === "PASS" ? theme.success : s === "RUNNING" ? theme.primary : s === "FAILED" ? theme.error : theme.textMuted

  const critical = createMemo(() => data()?.findings.filter((f) => f.severity >= 4).length ?? 0)
  const high = createMemo(() => data()?.findings.filter((f) => f.severity === 3).length ?? 0)
  const medium = createMemo(() => data()?.findings.filter((f) => f.severity === 2).length ?? 0)
  const low = createMemo(() => data()?.findings.filter((f) => f.severity <= 1).length ?? 0)

  const sevLabel = (s: number) => ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"][s] ?? "UNKNOWN"

  return (
    <box flexDirection="column" paddingX={2} paddingTop={1} flexGrow={1}>
      <box flexDirection="row" gap={1}>
        <text fg={theme.text}>Assessment</text>
        <text fg={theme.textMuted}>{route.target}</text>
      </box>
      <Show when={!loading() && !error()} fallback={
        <Show when={loading()}><text fg={theme.primary}>⠋ Loading...</text></Show>
      }>
        <box flexDirection="row" gap={2}>
          <text fg={statusColor(data()!.status)}>●</text>
          <text fg={theme.text}>{(data()?.status ?? "").toLowerCase()}</text>
          <text fg={theme.textMuted}>Engagement: {data()?.id}</text>
        </box>
        {/* Findings counters */}
        <box flexDirection="row" gap={2}>
          <text fg={theme.error}>{critical()} critical</text>
          <text fg={theme.warning}>{high()} high</text>
          <text fg={theme.primary}>{medium()} medium</text>
          <text fg={theme.textMuted}>{low()} low</text>
        </box>
        {/* Phase list */}
        <text fg={theme.textMuted}>Phases</text>
        <For each={data()?.phases ?? []}>
          {(phase) => (
            <box flexDirection="row" gap={1}>
              <text fg={statusColor(phase.status)}>
                {phase.status === "RUNNING" ? "⠋" : phase.status === "COMPLETED" ? "✓" : phase.status === "FAILED" ? "✗" : "○"}
              </text>
              <text fg={theme.text}>{phase.name}</text>
              <text fg={statusColor(phase.status)}>{phase.status.toLowerCase()}</text>
              <Show when={phase.errors.length > 0}>
                <text fg={theme.error}>⚠ {phase.errors.join("; ")}</text>
              </Show>
            </box>
          )}
        </For>
        {/* Finding entries */}
        <Show when={(data()?.findings.length ?? 0) > 0}>
          <text fg={theme.textMuted}>Findings ({data()?.findings.length})</text>
          <For each={data()?.findings.slice(0, 10) ?? []}>
            {(finding) => (
              <box flexDirection="row" gap={1}>
                <text fg={severityColor(finding.severity)}>[{sevLabel(finding.severity)}]</text>
                <text fg={theme.text}>{finding.title}</text>
                <text fg={theme.textMuted}>({finding.tool})</text>
              </box>
            )}
          </For>
          <Show when={(data()?.findings.length ?? 0) > 10}>
            <text fg={theme.textMuted}>... and {(data()?.findings.length ?? 0) - 10} more</text>
          </Show>
        </Show>
      </Show>
      <Show when={error() !== null}>
        <box flexDirection="row" gap={1}>
          <text fg={theme.error}>✗</text>
          <text fg={theme.text}>{error()}</text>
        </box>
      </Show>
      <box flexGrow={1} />
      <Toast />
    </box>
  )
}
export default ScanDashboard
