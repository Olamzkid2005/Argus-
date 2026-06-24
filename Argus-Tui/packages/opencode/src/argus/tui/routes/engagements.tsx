/**
 * Engagement Browser — List, filter, and open past engagements.
 *
 * Shows all engagements from the store with status, finding counts,
 * and quick actions to view details, reports, or resume.
 */
import { createSignal, createMemo, onMount, For, Show } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { useRoute } from "@tui/context/route"
import { Toast, useToast } from "@tui/ui/toast"

interface EngagementRow {
  id: string
  target: string
  workflow: string
  status: string
  findingCount: number
  createdAt: number
  updatedAt: number
}

export function EngagementBrowser() {
  const { theme } = useTheme()
  const route = useRoute()
  const [engagements, setEngagements] = createSignal<EngagementRow[]>([])
  const [loading, setLoading] = createSignal(true)
  const [filter, setFilter] = createSignal<string>("all")
  const toast = useToast()

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const list = store.listEngagements()

      // Single grouped query instead of N+1
      const ids = list.map((e) => e.id)
      const countsByEngId = store.getFindingCountsByEngagementIds(ids)

      const rows = list.map((e) => {
        const counts = countsByEngId.get(e.id)
        return {
          id: e.id, target: e.target, workflow: e.workflow, status: e.status,
          findingCount: counts?.total ?? 0, createdAt: +e.createdAt, updatedAt: +e.updatedAt,
        }
      })
      setEngagements(rows)
      setLoading(false)
    } catch (e) {
      toast.error(e)
      setLoading(false)
    }
  })

  const filtered = createMemo(() => {
    const f = filter()
    const items = engagements()
    if (f === "running") return items.filter((e) => e.status === "RUNNING")
    if (f === "completed") return items.filter((e) => e.status === "COMPLETED")
    if (f === "failed") return items.filter((e) => e.status === "FAILED")
    return items
  })

  const statusIcon = (s: string) =>
    s === "COMPLETED" ? "✓" : s === "RUNNING" ? "⟳" : s === "FAILED" ? "✗" : "○"

  const statusColor = (s: string) =>
    s === "COMPLETED" ? theme.success : s === "RUNNING" ? theme.primary : s === "FAILED" ? theme.error : theme.textMuted

  const formatDate = (ts: number) => {
    const d = new Date(ts)
    return d.toISOString().slice(0, 10)
  }

  const counts = createMemo(() => ({
    all: engagements().length,
    running: engagements().filter((e) => e.status === "RUNNING").length,
    completed: engagements().filter((e) => e.status === "COMPLETED").length,
    failed: engagements().filter((e) => e.status === "FAILED").length,
  }))

  return (
    <box flexDirection="column" paddingX={2} paddingTop={1} flexGrow={1}>
      <text fg={theme.text}>Engagements</text>

      {/* Filter tabs */}
      <box flexDirection="row" gap={1} paddingTop={1}>
        <box {...({ onClick: () => setFilter("all") } as any)}>
          <text fg={filter() === "all" ? theme.primary : theme.textMuted}>
            All ({counts().all})
          </text>
        </box>
        <box {...({ onClick: () => setFilter("running") } as any)}>
          <text fg={filter() === "running" ? theme.primary : theme.textMuted}>
            Running ({counts().running})
          </text>
        </box>
        <box {...({ onClick: () => setFilter("completed") } as any)}>
          <text fg={filter() === "completed" ? theme.primary : theme.textMuted}>
            Completed ({counts().completed})
          </text>
        </box>
        <box {...({ onClick: () => setFilter("failed") } as any)}>
          <text fg={filter() === "failed" ? theme.primary : theme.textMuted}>
            Failed ({counts().failed})
          </text>
        </box>
      </box>

      {/* Engagement list */}
      <Show when={!loading()} fallback={<text fg={theme.primary}>⠋ Loading...</text>}>
        <Show when={filtered().length > 0} fallback={
          <text fg={theme.textMuted} paddingTop={2}>No engagements match this filter.</text>
        }>
          <For each={filtered()}>
            {(eng) => (
              <box
                flexDirection="row"
                gap={1}
                paddingTop={1}
                border={["bottom"]}
                borderColor={theme.textMuted}
                {...({ onClick: () => route.navigate({ type: "engagement", engagementId: eng.id } as any) } as any)}
              >
                <text fg={statusColor(eng.status)}>{statusIcon(eng.status)}</text>
                <text fg={theme.textMuted}>{eng.id}</text>
                <text fg={theme.text}><b>{eng.target}</b></text>
                <text fg={theme.textMuted}>{eng.workflow}</text>
                <text fg={statusColor(eng.status)}>{eng.status.toLowerCase()}</text>
                <text fg={theme.textMuted}>{eng.findingCount} findings</text>
                <text fg={theme.textMuted}>{formatDate(eng.updatedAt)}</text>
              </box>
            )}
          </For>
          <text fg={theme.textMuted} paddingTop={1}>Enter to open</text>
        </Show>
      </Show>

      <box flexGrow={1} />
      <Toast />
    </box>
  )
}
export default EngagementBrowser
