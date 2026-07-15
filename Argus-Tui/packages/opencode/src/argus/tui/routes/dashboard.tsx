/**
 * Argus Dashboard — Home screen for the Argus Security Platform TUI.
 *
 * Shows key metrics, recent engagements, and quick actions.
 * This replaces the chat-based Home route as the primary landing page.
 */
import { createSignal, onMount, For, Show, createResource } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { useRoute } from "@tui/context/route"
import { Toast, useToast } from "@tui/ui/toast"
import { Tooltip } from "@tui/ui/tooltip"

/** Read the current planner model from env vars — same pattern as the inline reads in the status bar. */
function getCurrentModel(): string {
  return process.env.ARGUS_PLANNER_MODEL?.trim() || process.env.OPENCODE_MODEL?.trim() || "gpt-4o-mini"
}

interface EngagementSummary {
  id: string
  target: string
  status: string
  findingCount: number
  updatedAt: number
  plannerModel: string
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
  const toast = useToast()

  const [encryptionStatus] = createResource(async () => {
    try {
      const { EncryptionManager } = await import("@/argus/storage/encryption")
      // Use isInitialized() only — it checks whether a key *exists* without
      // retrieving it from the OS keychain, avoiding an auth prompt on mount.
      // Full detail (fingerprint, keychain vs file) is available via the
      // /encryption status slash command when the user explicitly asks for it.
      const initialized = await EncryptionManager.isInitialized()
      if (!initialized) {
        return { ready: false, fileBased: false }
      }
      return {
        ready: true,
        fileBased: EncryptionManager.isFileBased(),
      }
    } catch {
      return { ready: false, fileBased: false }
    }
  })

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const engagements = store.listEngagements()
      const totalTargets = new Set(engagements.map((e) => e.target)).size
      const openEngagements = engagements.filter((e) => e.status === "RUNNING" || e.status === "CREATED").length

      // Single grouped query instead of N+1
      const recentIds = engagements.slice(0, 8).map((e) => e.id)
      const countsByEngId = store.getFindingCountsByEngagementIds(recentIds)

      let confirmedFindings = 0
      const recent = engagements.slice(0, 8).map((e) => {
        const counts = countsByEngId.get(e.id)
        const findingCount = counts?.total ?? 0
        confirmedFindings += counts?.confirmed ?? 0
        return { id: e.id, target: e.target, status: e.status, findingCount, updatedAt: +e.updatedAt, plannerModel: getCurrentModel() }
      })
      setData({ totalTargets, openEngagements, confirmedFindings, recent })
      setLoading(false)
    } catch (e) {
      toast.error(e)
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
                {...({ onClick: () => {
                  // Validate target URL before navigating to scan route
                  // Malformed targets ("foo", "javascript:...", "") would break the scan dashboard
                  try {
                    new URL(eng.target)
                  } catch {
                    toast.error(`Invalid target URL: ${eng.target}`)
                    return
                  }
                  route.navigate({ type: "scan", target: eng.target, engagementId: eng.id })
                } } as any)}
              >
                <text fg={statusColor(eng.status)}>{statusIcon(eng.status)}</text>
                <text fg={theme.textMuted}>{eng.id}</text>
                <text fg={theme.text}>{eng.target}</text>
                <text fg={statusColor(eng.status)}>{eng.status.toLowerCase()}</text>
                <text fg={theme.textMuted}>({eng.findingCount} findings)</text>
                {/* Model used for this assessment */}
                <Show when={process.env.OPENAI_API_KEY || process.env.ANTHROPIC_API_KEY || process.env.OPENCODE_API_KEY}>
                  <Tooltip
                    value={
                      <box flexDirection="column" gap={1}>
                        <text fg={theme.text}><b>Assessment Model</b></text>
                        <text fg={theme.textMuted}>{`ARGUS_PLANNER_MODEL=${eng.plannerModel}`}</text>
                      </box>
                    }
                    placement="bottom"
                    gutter={4}
                  >
                    <text fg={theme.textMuted}>{eng.plannerModel}</text>
                  </Tooltip>
                </Show>
              </box>
            )}
          </For>
        </Show>

        {/* Status bar */}
        <box flexGrow={1} />
        <box flexDirection="row" justifyContent="space-between" border={["top"]} borderColor={theme.textMuted} paddingTop={1}>
          <box flexDirection="row" gap={2}>
            <text fg={theme.textMuted}>ARGUS v5</text>
            {/* Subtle LLM model indicator — shows configured planner model when API key is present, with hover tooltip for full env config */}
            <Show when={process.env.OPENAI_API_KEY || process.env.ANTHROPIC_API_KEY || process.env.OPENCODE_API_KEY}>
              <Tooltip
                value={
                  <box flexDirection="column" gap={1}>
                    <text fg={theme.text}><b>Planner Model</b></text>
                    <text fg={theme.textMuted}>{`ARGUS_PLANNER_MODEL=${getCurrentModel()} (default: gpt-4o-mini, supports OpenAI-compatible and Anthropic models)`}</text>
                  </box>
                }
                placement="bottom"
                gutter={4}
              >
                <text fg={theme.textMuted}>{getCurrentModel()}</text>
              </Tooltip>
            </Show>
          </box>
          <box flexDirection="row" gap={2}>
            {/* Encryption indicator — uses isInitialized() only, avoids OS keychain auth prompt */}
            <Show when={encryptionStatus() !== undefined}>
              <Show
                when={encryptionStatus()?.ready}
                fallback={<text fg={theme.textMuted}>○ No encryption key</text>}
              >
                <text fg={theme.success}>🔒 Key present</text>
              </Show>
            </Show>
            <text fg={theme.success}>● Ready</text>
          </box>
        </box>
      </Show>
      <Toast />
    </box>
  )
}
export default ArgusDashboard
