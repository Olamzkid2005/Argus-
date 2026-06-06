/**
 * Scan Dashboard — Real-time assessment progress and results.
 *
 * Shows live phase progress, finding severity breakdown, and
 * a detailed finding list. Polls the EngagementStore while
 * the assessment is running.
 */
import { createMemo, createSignal, onMount, For, Show, onCleanup } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { Toast } from "@tui/ui/toast"
import { useRouteData } from "@tui/context/route"
import { handleProgressEvent as scanHandleProgress } from "../scan-store"

interface EngPhase { id: string; name: string; status: string; error?: string }
interface EngFinding { title: string; severity: number; confidence: number; tool: string; description?: string }
interface EngagementData {
  id: string; target: string; status: string
  phases: Array<{ name: string; status: string; errors: string[] }>
  findings: EngFinding[]
}

function sevLabel(s: number): string {
  return ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"][s] ?? "UNKNOWN"
}

function sevShort(s: number): string {
  return ["I", "L", "M", "H", "C"][s] ?? "?"
}

function phaseIcon(status: string): string {
  switch (status) {
    case "COMPLETED": case "PASS": return "✓"
    case "RUNNING": return "⟳"
    case "FAILED": return "✗"
    case "PENDING": return "○"
    default: return "○"
  }
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
        phases: engPhases.map((p) => ({ name: p.name || p.id, status: p.status, errors: p.error ? [p.error] : [] })),
        findings: engFindings.map((f) => ({
          title: f.title, severity: f.severity ?? 0, confidence: f.confidence ?? 0,
          tool: f.tool, description: (f.description ?? "").slice(0, 300),
        })),
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
            setData((prev) => prev ? {
              ...prev, status: updated.status,
              phases: uPhases.map((p) => ({ name: p.name || p.id, status: p.status, errors: p.error ? [p.error] : [] })),
              findings: uFindings.map((f) => ({
                title: f.title, severity: f.severity ?? 0, confidence: f.confidence ?? 0,
                tool: f.tool, description: (f.description ?? "").slice(0, 300),
              })),
            } : null)
            if (updated.status === "COMPLETED" || updated.status === "FAILED") clearInterval(interval)
          } catch (e) { console.error("Poll error:", e) }
        }, pollCount < 5 ? 1000 : 5000)
        onCleanup(() => clearInterval(interval))
      }
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to load"); setLoading(false) }
  }
  onMount(loadData)

  const severityColor = (s: number) =>
    s >= 4 ? theme.error : s >= 3 ? theme.warning : s >= 2 ? theme.primary : theme.textMuted
  const statusColor = (s: string) =>
    s === "COMPLETED" || s === "PASS" ? theme.success : s === "RUNNING" ? theme.primary : s === "FAILED" ? theme.error : theme.textMuted

  const completedPhases = createMemo(() => data()?.phases.filter((p) => p.status === "COMPLETED").length ?? 0)
  const totalPhases = createMemo(() => data()?.phases.length ?? 0)
  const progressPct = createMemo(() => totalPhases() > 0 ? Math.round((completedPhases() / totalPhases()) * 100) : 0)

  const critical = createMemo(() => data()?.findings.filter((f) => f.severity >= 4).length ?? 0)
  const high = createMemo(() => data()?.findings.filter((f) => f.severity === 3).length ?? 0)
  const medium = createMemo(() => data()?.findings.filter((f) => f.severity === 2).length ?? 0)
  const low = createMemo(() => data()?.findings.filter((f) => f.severity <= 1).length ?? 0)
  const totalFindingCount = createMemo(() => data()?.findings.length ?? 0)

  // Progress bar characters
  const barWidth = 30
  const filledBars = createMemo(() => Math.round((progressPct() / 100) * barWidth))
  const emptyBars = createMemo(() => barWidth - filledBars())
  const barFilled = "█".repeat(filledBars())
  const barEmpty = "░".repeat(emptyBars())

  return (
    <box flexDirection="column" paddingX={2} paddingTop={1} flexGrow={1}>
      {/* Header row: assessment title + status */}
      <box flexDirection="row" gap={1} paddingBottom={1}>
        <text fg={theme.text} bold>Assessment</text>
        <text fg={theme.textMuted}>{data()?.target ?? route.target}</text>
        <Show when={data()}>
          <text fg={statusColor(data()!.status)}>
            {phaseIcon(data()!.status)} {data()!.status.toLowerCase()}
          </text>
        </Show>
      </box>

      <Show when={!loading() && !error()} fallback={
        <Show when={loading()}><text fg={theme.primary}>⠋ Loading...</text></Show>
      }>
        {/* Progress bar */}
        <box flexDirection="row" gap={1} paddingBottom={1}>
          <text fg={theme.primary}>{barFilled}</text>
          <text fg={theme.textMuted}>{barEmpty}</text>
          <text fg={theme.text}>{progressPct()}%</text>
          <text fg={theme.textMuted}>({completedPhases()}/{totalPhases()} phases)</text>
        </box>

        {/* Finding severity summary box */}
        <box
          border={{ type: "round", fg: theme.textMuted }}
          paddingX={1}
          paddingY={1}
          marginBottom={1}
        >
          <box flexDirection="row" gap={2}>
            <box flexDirection="column" alignItems="center">
              <text fg={theme.error} bold>{critical()}</text>
              <text fg={theme.textMuted}>critical</text>
            </box>
            <box flexDirection="column" alignItems="center">
              <text fg={theme.warning} bold>{high()}</text>
              <text fg={theme.textMuted}>high</text>
            </box>
            <box flexDirection="column" alignItems="center">
              <text fg={theme.primary} bold>{medium()}</text>
              <text fg={theme.textMuted}>medium</text>
            </box>
            <box flexDirection="column" alignItems="center">
              <text fg={theme.text} bold>{low()}</text>
              <text fg={theme.textMuted}>low</text>
            </box>
            <box border={{ type: "left", fg: theme.textMuted }} paddingLeft={1} flexDirection="column" alignItems="center">
              <text fg={theme.text} bold>{totalFindingCount()}</text>
              <text fg={theme.textMuted}>total</text>
            </box>
          </box>
        </box>

        {/* Phase list with workflow icons */}
        <text fg={theme.textMuted}>Workflow Phases</text>
        <For each={data()?.phases ?? []}>
          {(phase) => (
            <box flexDirection="row" gap={1}>
              <text fg={statusColor(phase.status)}>{phaseIcon(phase.status)}</text>
              <text fg={theme.text}>{phase.name}</text>
              <text fg={statusColor(phase.status)}>{phase.status.toLowerCase()}</text>
              <Show when={phase.errors.length > 0}>
                <text fg={theme.error}>⚠ {phase.errors.join("; ")}</text>
              </Show>
            </box>
          )}
        </For>

        {/* Finding entries with severity badges */}
        <Show when={totalFindingCount() > 0}>
          <text fg={theme.textMuted} paddingTop={1}>Findings ({totalFindingCount()})</text>
          <For each={data()?.findings.slice(0, 15) ?? []}>
            {(finding) => (
              <box flexDirection="column" paddingTop={1}>
                <box flexDirection="row" gap={1}>
                  <text
                    fg={severityColor(finding.severity)}
                    bold
                  >
                    [{sevShort(finding.severity)}]
                  </text>
                  <text fg={severityColor(finding.severity)}>
                    {sevLabel(finding.severity)}
                  </text>
                  <text fg={theme.text}>{finding.title}</text>
                  <text fg={theme.textMuted}>({finding.tool})</text>
                </box>
                <Show when={finding.description}>
                  <text fg={theme.textMuted} paddingLeft={6}>
                    {finding.description}
                  </text>
                </Show>
              </box>
            )}
          </For>
          <Show when={totalFindingCount() > 15}>
            <text fg={theme.textMuted} paddingTop={1}>
              ... and {totalFindingCount() - 15} more findings
            </text>
          </Show>
        </Show>
      </Show>

      {/* Error state */}
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
