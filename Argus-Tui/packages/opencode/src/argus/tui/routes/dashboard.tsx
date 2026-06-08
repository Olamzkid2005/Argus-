/**
 * Argus Dashboard — Home screen for the Argus Security Platform TUI.
 *
 * Shows key metrics, recent engagements, and quick actions.
 * This replaces the chat-based Home route as the primary landing page.
 */
import { createSignal, onMount, For, Show } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { useRoute } from "@tui/context/route"

interface EngagementSummary {
  id: string
  target: string
  status: string
  findingCount: number
  updatedAt: number
}

interface DashboardData {
  totalTargets: number
  openEngagements: number
  confirmedFindings: number
  recent: EngagementSummary[]
}

export function ArgusDashboard() {
  const { theme } = useTheme()
  const route = useRoute()
  const [data, setData] = createSignal<DashboardData | null>(null)
  const [loading, setLoading] = createSignal(true)

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const engagements = store.listEngagements()
      const totalTargets = new Set(engagements.map((e) => e.target)).size
      const openEngagements = engagements.filter((e) => e.status === "RUNNING" || e.status === "CREATED").length
      let confirmedFindings = 0
      const recent = engagements.slice(0, 8).map((e) => {
        const findings = store.getFindings(e.id)
        confirmedFindings += findings.filter((f) => f.status === "CONFIRMED" || f.status === "FINALIZED").length
        return { id: e.id, target: e.target, status: e.status, findingCount: findings.length, updatedAt: +e.updatedAt }
      })
      setData({ totalTargets, openEngagements, confirmedFindings, recent })
      setLoading(false)
    } catch {
      setLoading(false)
    }
  })

  const statusIcon = (s: string) =>
    s === "COMPLETED" ? "✓" : s === "RUNNING" ? "⟳" : s === "FAILED" ? "✗" : "○"

  const statusColor = (s: string) =>
    s === "COMPLETED" ? theme.success : s === "RUNNING" ? theme.primary : s === "FAILED" ? theme.error : theme.textMuted

  return (
    <box flexDirection="column" paddingX={2} paddingTop={1} flexGrow={1}>
      <Show when={!loading()} fallback={<text fg={theme.primary}>⠋ Loading...</text>}>
        {/* Stats row */}
        <box flexDirection="row" gap={3} paddingTop={1} paddingBottom={1}>
          <box flexDirection="column" alignItems="center">
            <text fg={theme.text}>
              <b>{(data()?.totalTargets ?? 0).toString()}</b>
            </text>
            <text fg={theme.textMuted}>targets</text>
          </box>
          <box flexDirection="column" alignItems="center">
            <text fg={theme.warning}>
              <b>{(data()?.openEngagements ?? 0).toString()}</b>
            </text>
            <text fg={theme.textMuted}>active</text>
          </box>
          <box flexDirection="column" alignItems="center">
            <text fg={theme.error}>
              <b>{(data()?.confirmedFindings ?? 0).toString()}</b>
            </text>
            <text fg={theme.textMuted}>findings</text>
          </box>
        </box>

        {/* Quick actions — text labels, not buttons (CLI commands are the real entry point) */}
        <text fg={theme.textMuted}>Quick Actions</text>
        <box flexDirection="row" gap={1} paddingTop={1}>
          <text fg={theme.primary}>/assess {'<target>'}</text>
          <text fg={theme.textMuted}>|</text>
          <text fg={theme.textMuted}>/engagements</text>
          <text fg={theme.textMuted}>|</text>
          <text fg={theme.textMuted}>/doctor</text>
          <text fg={theme.textMuted}>|</text>
          <text fg={theme.textMuted}>/workspace</text>
        </box>

        {/* Recent engagements */}
        <text fg={theme.textMuted} paddingTop={2}>Recent Activity</text>
        <Show when={(data()?.recent.length ?? 0) > 0} fallback={
          <text fg={theme.textMuted}>No assessments yet. Run /assess to get started.</text>
        }>
          <For each={data()?.recent ?? []}>
            {(eng) => (
              <box
                flexDirection="row"
                gap={1}
                paddingTop={1}
                {...({ onClick: () => route.navigate({ type: "scan", target: eng.target, engagementId: eng.id }) } as any)}
              >
                <text fg={statusColor(eng.status)}>{statusIcon(eng.status)}</text>
                <text fg={theme.textMuted}>{eng.id}</text>
                <text fg={theme.text}>{eng.target}</text>
                <text fg={statusColor(eng.status)}>{eng.status.toLowerCase()}</text>
                <text fg={theme.textMuted}>({eng.findingCount} findings)</text>
              </box>
            )}
          </For>
        </Show>

        {/* Status bar */}
        <box flexGrow={1} />
        <box flexDirection="row" justifyContent="space-between" border={["top"]} borderColor={theme.textMuted} paddingTop={1}>
          <text fg={theme.textMuted}>ARGUS v5</text>
          <text fg={theme.success}>● Ready</text>
        </box>
      </Show>
    </box>
  )
}
export default ArgusDashboard
