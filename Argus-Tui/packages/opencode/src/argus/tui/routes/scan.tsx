/**
 * Scan Dashboard — Real-time assessment progress and results.
 *
 * Shows live phase progress, findings as they're discovered,
 * and a results summary when the assessment completes.
 */

import { createMemo, createSignal, onMount, For, Show, onCleanup } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { Toast } from "@tui/ui/toast"
import { useRouteData } from "@tui/context/route"

interface EngPhase {
  id: string
  name: string
  status: string
  error?: string
}
interface EngFinding {
  title: string
  severity: number
  confidence: number
  tool: string
  description?: string
  phase?: string
}
interface EngagementData {
  id: string
  target: string
  status: string
  phases: Array<{ name: string; status: string; errors: string[] }>
  findings: EngFinding[]
  duration: number
}

export function ScanDashboard() {
  const route = useRouteData("scan")
  const { theme } = useTheme()
  const dimensions = useTerminalDimensions()
  const [data, setData] = createSignal<EngagementData | null>(null)
  const [loading, setLoading] = createSignal(true)
  const [error, setError] = createSignal<string | null>(null)

  // Load engagement data
  const loadData = async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const engagement = store.getEngagement(route.engagementId)
      if (!engagement) {
        setError("Engagement not found")
        setLoading(false)
        return
      }
      const engPhases = store.getPhases(route.engagementId) as EngPhase[]
      const engFindings = store.getFindings(route.engagementId) as EngFinding[]
      setData({
        id: engagement.id,
        target: engagement.target,
        status: engagement.status,
        phases: engPhases.map((p: EngPhase) => ({
          name: p.name || p.id,
          status: p.status,
          errors: p.error ? [p.error] : [],
        })),
        findings: engFindings.map((f: EngFinding) => ({
          title: f.title,
          severity: f.severity ?? 0,
          confidence: f.confidence ?? 0,
          tool: f.tool,
        })),
        duration: 0,
      })
      setLoading(false)

      // Poll for updates if running
      if (engagement.status === "RUNNING" || engagement.status === "ACTIVE") {
        let pollCount = 0
        const interval = setInterval(async () => {
          pollCount++
          try {
            const updated = store.getEngagement(route.engagementId)
            if (!updated) return
            const uPhases = store.getPhases(route.engagementId) as EngPhase[]
            const uFindings = store.getFindings(route.engagementId) as EngFinding[]
            setData((prev) => prev ? {
              ...prev,
              status: updated.status,
              phases: uPhases.map((p: EngPhase) => ({
                name: p.name || p.id,
                status: p.status,
                errors: p.error ? [p.error] : [],
              })),
              findings: uFindings.map((f: EngFinding) => ({
                title: f.title,
                severity: f.severity ?? 0,
                confidence: f.confidence ?? 0,
                tool: f.tool,
              })),
            } : null)
            if (updated.status === "COMPLETED" || updated.status === "FAILED") {
              clearInterval(interval)
            }
          } catch (pollErr) {
            console.error("Scan poll error:", pollErr)
          }
        }, pollCount < 5 ? 1000 : 5000)
        onCleanup(() => clearInterval(interval))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load engagement")
      setLoading(false)
    }
  }

  onMount(loadData)

  const severityLabel = (s: number) => ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"][s] ?? "UNKNOWN"
  const severityColor = (s: number) => {
    if (s >= 4) return theme.error as string
    if (s >= 3) return theme.warning as string
    if (s >= 2) return theme.primary as string
    return theme.textMuted as string
  }
  const statusColor = (s: string) => {
    if (s === "COMPLETED" || s === "PASS") return theme.success as string
    if (s === "RUNNING" || s === "ACTIVE") return theme.primary as string
    if (s === "FAILED") return theme.error as string
    return theme.textMuted as string
  }

  const critical = createMemo(() => data()?.findings.filter((f) => f.severity >= 4).length ?? 0)
  const high = createMemo(() => data()?.findings.filter((f) => f.severity === 3).length ?? 0)
  const medium = createMemo(() => data()?.findings.filter((f) => f.severity === 2).length ?? 0)
  const low = createMemo(() => data()?.findings.filter((f) => f.severity <= 1).length ?? 0)

  return (
    <box flexDirection="column" paddingX={2} paddingTop={1} flexGrow={1}>
      {/* Header */}
      <box flexDirection="row" gap={1} paddingBottom={1}>
        <text fg={theme.text} font="mono" attributes={{ bold: true }}>Assessment</text>
        <text fg={theme.textMuted} font="mono">{route.target}</text>
      </box>

      <Show when={!loading() && !error() && data() !== null}>
        {(d) => (
          <>
            {/* Status bar */}
            <box flexDirection="row" gap={2} paddingY={0.5}>
              <box flexDirection="row" gap={0.5}>
                <text fg={statusColor(d().status) as any} font="mono">●</text>
                <text fg={theme.text} font="mono">{d().status.toLowerCase()}</text>
              </box>
              <text fg={theme.textMuted} font="mono">Engagement: {d().id}</text>
            </box>

            {/* Findings summary */}
            <box flexDirection="row" gap={2} paddingY={0.5}>
              <box flexDirection="row" gap={0.5}>
                <text fg="#ef4444" font="mono">{critical()}</text>
                <text fg={theme.textMuted} font="mono">critical</text>
              </box>
              <box flexDirection="row" gap={0.5}>
                <text fg="#f59e0b" font="mono">{high()}</text>
                <text fg={theme.textMuted} font="mono">high</text>
              </box>
              <box flexDirection="row" gap={0.5}>
                <text fg="#00bcd4" font="mono">{medium()}</text>
                <text fg={theme.textMuted} font="mono">medium</text>
              </box>
              <box flexDirection="row" gap={0.5}>
                <text fg={theme.textMuted} font="mono">{low()}</text>
                <text fg={theme.textMuted} font="mono">low</text>
              </box>
            </box>

            {/* Phase timeline */}
            <box paddingY={0.5}>
              <text fg={theme.textMuted} font="mono" attributes={{ bold: true }}>Phases</text>
            </box>
            <For each={d().phases}>
              {(phase) => (
                <box flexDirection="row" gap={1} paddingY={0.2}>
                  <text fg={statusColor(phase.status) as any} font="mono">
                    {phase.status === "running" || phase.status === "RUNNING" ? "⠋"
                      : phase.status === "COMPLETED" || phase.status === "PASS" ? "✓"
                      : phase.status === "FAILED" ? "✗"
                      : "○"}
                  </text>
                  <text fg={theme.text} font="mono">{phase.name}</text>
                  <text fg={statusColor(phase.status) as any} font="mono" size="small">
                    {phase.status.toLowerCase()}
                  </text>
                  <Show when={phase.errors.length > 0}>
                    <text fg="#ef4444" font="mono" size="small">⚠ {phase.errors.join("; ")}</text>
                  </Show>
                </box>
              )}
            </For>

            {/* Findings list */}
            <Show when={d().findings.length > 0}>
              <box paddingY={0.5} paddingTop={1}>
                <text fg={theme.textMuted} font="mono" attributes={{ bold: true }}>
                  Findings ({d().findings.length})
                </text>
              </box>
              <For each={d().findings.slice(0, 10)}>
                {(finding) => (
                  <box flexDirection="row" gap={1} paddingY={0.15}>
                    <text fg={severityColor(finding.severity) as any} font="mono" size="small">
                      [{severityLabel(finding.severity)}]
                    </text>
                    <text fg={theme.text} font="mono" size="small">{finding.title}</text>
                    <text fg={theme.textMuted} font="mono" size="small">({finding.tool})</text>
                  </box>
                )}
              </For>
              <Show when={d().findings.length > 10}>
                <text fg={theme.textMuted} font="mono" size="small">
                  ... and {d().findings.length - 10} more
                </text>
              </Show>
            </Show>
          </>
        )}
      </Show>

      {/* Loading state */}
      <Show when={loading()}>
        <box flexDirection="row" gap={1} paddingTop={2}>
          <text fg={theme.primary as any} font="mono">⠋</text>
          <text fg={theme.textMuted} font="mono">Loading assessment data...</text>
        </box>
      </Show>

      {/* Error state */}
      <Show when={error()}>
        <box flexDirection="row" gap={1} paddingTop={2}>
          <text fg="#ef4444" font="mono">✗</text>
          <text fg={theme.text} font="mono">{error()}</text>
        </box>
      </Show>

      <box flexGrow={1} />
      <Toast />
    </box>
  )
}

export default ScanDashboard
