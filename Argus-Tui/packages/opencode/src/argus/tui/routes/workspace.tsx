/**
 * Workspace — Central navigation hub for assessment operations.
 *
 * Shows key metrics and quick links to all assessment resources.
 * The primary navigation hub for the Argus platform.
 */
import { createSignal, onMount, Show } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { useRoute } from "@tui/context/route"
import { Toast, useToast } from "@tui/ui/toast"

export function Workspace() {
  const { theme } = useTheme()
  const route = useRoute()
  const [engCount, setEngCount] = createSignal(0)
  const [runningCount, setRunningCount] = createSignal(0)
  const [findingCount, setFindingCount] = createSignal(0)
  const [criticalCount, setCriticalCount] = createSignal(0)
  const [loading, setLoading] = createSignal(true)
  const toast = useToast()

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const engs = store.listEngagements()

      // Single grouped query instead of N+1 (one query for all engagements)
      const ids = engs.map((e) => e.id)
      const countsByEngId = store.getFindingCountsByEngagementIds(ids)

      let findings = 0, critical = 0, running = 0
      for (const e of engs) {
        if (e.status === "RUNNING") running++
        const counts = countsByEngId.get(e.id)
        if (counts) {
          findings += counts.total
          critical += counts.critical
        }
      }
      setEngCount(engs.length)
      setRunningCount(running)
      setFindingCount(findings)
      setCriticalCount(critical)
      setLoading(false)
    } catch (e) { toast.error(e); setLoading(false) }
  })

  return (
    <box flexDirection="column" paddingX={2} paddingTop={1} flexGrow={1}>
      <text fg={theme.text}>Workspace</text>
      <text fg={theme.textMuted} paddingTop={1}>Assessment Operations Center</text>

      <Show when={!loading()}>
        {/* Metric cards row */}
        <box flexDirection="row" gap={2} paddingTop={2}>
          <box
            flexDirection="column"
            borderStyle="rounded" border
            borderColor={theme.primary}
            paddingX={2} paddingY={1} flexGrow={1}
          >
            <text fg={theme.primary}><b>{engCount()}</b></text>
            <text fg={theme.primary}>Engagements</text>
            <text fg={theme.textMuted}>Total assessments</text>
          </box>
          <box
            flexDirection="column"
            borderStyle="rounded" border
            borderColor={theme.warning}
            paddingX={2} paddingY={1} flexGrow={1}
          >
            <text fg={theme.warning}><b>{runningCount()}</b></text>
            <text fg={theme.warning}>Running</text>
            <text fg={theme.textMuted}>Active scans</text>
          </box>
          <box
            flexDirection="column"
            borderStyle="rounded" border
            borderColor={theme.error}
            paddingX={2} paddingY={1} flexGrow={1}
          >
            <text fg={theme.error}><b>{findingCount()}</b></text>
            <text fg={theme.error}>Findings</text>
            <text fg={theme.textMuted}>Total discovered</text>
          </box>
          <box
            flexDirection="column"
            borderStyle="rounded" border
            borderColor={theme.error}
            paddingX={2} paddingY={1} flexGrow={1}
          >
            <text fg={theme.error}><b>{criticalCount()}</b></text>
            <text fg={theme.error}>Critical</text>
            <text fg={theme.textMuted}>Severity 4+</text>
          </box>
        </box>
      </Show>

      {/* Quick navigation */}
      <text fg={theme.textMuted} paddingTop={2}>Quick Navigation</text>
      <box flexDirection="row" gap={1} paddingTop={1}>
        <box borderStyle="rounded" border borderColor={theme.primary} paddingX={1}>
          <text fg={theme.primary}>/engagements</text>
        </box>
        <box borderStyle="rounded" border borderColor={theme.error} paddingX={1}>
          <text fg={theme.error}>/findings</text>
        </box>
        <box borderStyle="rounded" border borderColor={theme.success} paddingX={1}>
          <text fg={theme.success}>/doctor</text>
        </box>
        <box borderStyle="rounded" border borderColor={theme.textMuted} paddingX={1}>
          <text fg={theme.textMuted}>/config</text>
        </box>
      </box>

      <box flexGrow={1} />
      <Toast />
    </box>
  )
}
export default Workspace
