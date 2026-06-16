/**
 * Scan Dashboard — Real-time assessment progress and results.
 *
 * Shows live phase progress, finding severity breakdown, and
 * a detailed finding list. Uses reactive ScanStore signals for
 * instant updates instead of SQLite polling.
 *
 * On mount, pre-populates ScanStore from SQLite for persistence
 * recovery (e.g. reconnecting to a running engagement).
 */
import { createMemo, createSignal, onMount, For, Show, onCleanup } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { Toast } from "@tui/ui/toast"
import { useRouteData } from "@tui/context/route"
import { getScanState, initScan, addPhase, completePhase, resetScan } from "../scan-store"

const SPINNER_CHARS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

function phaseIcon(status: string): string {
  switch (status) {
    case "COMPLETED": case "PASS": return "✓"
    case "RUNNING": return "⟳"
    case "FAILED": return "✗"
    case "PENDING": return "○"
    default: return "○"
  }
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const m = Math.floor(ms / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  return `${m}m ${s}s`
}

export function ScanDashboard() {
  const route = useRouteData("scan")
  const { theme } = useTheme()
  const [loading, setLoading] = createSignal(true)
  const [error, setError] = createSignal<string | null>(null)

  // Reactive reads from ScanStore — updates instantly on mutation
  const scanState = getScanState()

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const engagement = store.getEngagement(route.engagementId)
      if (!engagement) {
        setError("Engagement not found")
        setLoading(false)
        return
      }

      // Pre-populate ScanStore from SQLite for persistence recovery
      resetScan()
      initScan(engagement.target, engagement.id)

      const engPhases = store.getPhases(route.engagementId) as Array<{ id: string; name: string; status: string; error?: string }>
      const totalFindings = store.getFindings(route.engagementId).length

      for (let i = 0; i < engPhases.length; i++) {
        const p = engPhases[i]
        addPhase({ id: p.id, name: p.name || p.id, index: i, total: engPhases.length })
        if (p.status === "COMPLETED" || p.status === "FAILED" || p.status === "PARTIAL") {
          const status = p.status === "PARTIAL" ? "partial" : p.status === "FAILED" ? "failed" : "completed"
          completePhase(i, 0, p.error ? [p.error] : [], status)
        }
      }

      // Set total findings count and scan status directly
      const { completeScan, setTotalFindings } = await import("../scan-store")
      setTotalFindings(totalFindings)
      if (engagement.status === "COMPLETED" || engagement.status === "FAILED") {
        completeScan(engagement.status !== "FAILED")
      }

      setLoading(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load")
      setLoading(false)
    }
  })

  onCleanup(() => {
    // Don't reset on cleanup — keeps last state visible
  })

  const statusColor = (s: string) =>
    s === "COMPLETED" || s === "PASS" ? theme.success : s === "RUNNING" ? theme.primary : s === "FAILED" ? theme.error : theme.textMuted

  // Derived memos from reactive ScanStore
  const completedPhases = createMemo(() => scanState.phases.filter((p) => p.status === "completed").length)
  const totalPhases = createMemo(() => scanState.phases.length)
  const progressPct = createMemo(() => totalPhases() > 0 ? Math.round((completedPhases() / totalPhases()) * 100) : 0)

  // Animated spinner for running phases
  const [spinnerIdx, setSpinnerIdx] = createSignal(0)
  onMount(() => {
    const interval = setInterval(() => {
      setSpinnerIdx((prev) => (prev + 1) % SPINNER_CHARS.length)
    }, 120)
    onCleanup(() => clearInterval(interval))
  })
  const spinner = createMemo(() => SPINNER_CHARS[spinnerIdx()])

  // Progress bar characters
  const barWidth = 30
  const filledBars = createMemo(() => Math.round((progressPct() / 100) * barWidth))
  const emptyBars = createMemo(() => barWidth - filledBars())
  const barFilled = createMemo(() => "█".repeat(filledBars()))
  const barEmpty = createMemo(() => "░".repeat(emptyBars()))

  // Running phase for highlighting
  const runningPhaseIndex = createMemo(() =>
    scanState.phases.findIndex((p) => p.status === "running")
  )

  return (
    <box flexDirection="column" paddingX={2} paddingTop={1} flexGrow={1}>
      {/* Header row: assessment title + status */}
      <box flexDirection="row" gap={1} paddingBottom={1}>
        <text fg={theme.text}><b>Assessment</b></text>
        <text fg={theme.textMuted}>{scanState.target || route.target}</text>
        <Show when={scanState.status === "running"}>
          <text fg={theme.primary}>{spinner()} Running</text>
        </Show>
        <Show when={scanState.status === "completed"}>
          <text fg={theme.success}>✓ Complete</text>
        </Show>
        <Show when={scanState.status === "failed"}>
          <text fg={theme.error}>✗ Failed</text>
        </Show>
      </box>

      <Show when={!loading() && !error()} fallback={
        <Show when={loading()}><text fg={theme.primary}>⠋ Loading...</text></Show>
      }>
        {/* Progress bar */}
        <box flexDirection="row" gap={1} paddingBottom={1}>
          <text fg={theme.primary}>{barFilled()}</text>
          <text fg={theme.textMuted}>{barEmpty()}</text>
          <text fg={theme.text}>{progressPct()}%</text>
          <text fg={theme.textMuted}>({completedPhases()}/{totalPhases()} phases)</text>
          <Show when={scanState.durationMs > 0}>
            <text fg={theme.textMuted}>• {formatDuration(scanState.durationMs)}</text>
          </Show>
        </box>

        {/* Finding severity summary box */}
        <box
          borderStyle="rounded"
          border
          borderColor={theme.textMuted}
          paddingX={1}
          paddingY={1}
          marginBottom={1}
        >
          <box flexDirection="row" gap={2}>
            <box flexDirection="column" alignItems="center">
              <text fg={theme.error}><b>{scanState.totalFindings}</b></text>
              <text fg={theme.textMuted}>findings</text>
            </box>
          </box>
        </box>

        {/* AI Analysis progress indicator */}
        <Show when={scanState.analysisTotal > 0}>
          <box flexDirection="row" gap={1} paddingBottom={1}>
            <Show
              when={scanState.analysisCurrent < scanState.analysisTotal}
              fallback={
                <text fg={theme.success}>✓ AI analysis complete ({scanState.analysisTotal} findings)</text>
              }
            >
              <text fg={theme.primary}>{spinner()} Analyzing findings: {scanState.analysisCurrent}/{scanState.analysisTotal}</text>
            </Show>
          </box>
        </Show>

        {/* Phase list with enhanced visualization */}
        <text fg={theme.textMuted} paddingBottom={1}>Workflow Phases</text>
        <For each={scanState.phases}>
          {(phase, idx) => {
            const isRunning = idx() === runningPhaseIndex()
            const statusUpper = phase.status.toUpperCase()
            return (
              <box
                flexDirection="column"
                paddingLeft={1}
                border={["left"]}
                borderColor={isRunning ? theme.primary : statusColor(statusUpper)}
              >
                <box flexDirection="row" gap={1}>
                  <text fg={isRunning ? theme.primary : statusColor(statusUpper)}>
                    {isRunning ? spinner() : phaseIcon(statusUpper)}
                  </text>
                  <text fg={theme.text}>{isRunning ? <b>{phase.name}</b> : phase.name}</text>
                  <Show when={isRunning}>
                    <text fg={theme.primary}>running</text>
                  </Show>
                  <Show when={phase.status === "completed"}>
                    <text fg={theme.success}>completed</text>
                    <Show when={phase.findings > 0}>
                      <text fg={theme.textMuted}>{phase.findings} finding(s)</text>
                    </Show>
                  </Show>
                  <Show when={phase.status === "failed"}>
                    <text fg={theme.error}>failed</text>
                  </Show>
                </box>
                <Show when={phase.errors.length > 0}>
                  <box flexDirection="row" gap={1} paddingLeft={3}>
                    <text fg={theme.error}>⚠ {phase.errors.join("; ")}</text>
                  </box>
                </Show>
              </box>
            )
          }}
        </For>

        {/* Log entries with timestamps */}
        <Show when={scanState.log.length > 0}>
          <text fg={theme.textMuted} paddingTop={1}>Activity Log</text>
          <For each={scanState.log.slice(-8)}>
            {(entry) => (
              <text fg={theme.textMuted}>{entry}</text>
            )}
          </For>
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
