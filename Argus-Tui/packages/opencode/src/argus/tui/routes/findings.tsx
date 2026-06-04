/**
 * Findings Viewer — Browse and filter assessment findings.
 */
import { createMemo, createSignal, onMount, For, Show } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { useRouteData } from "@tui/context/route"

export function FindingsViewer() {
  const route = useRouteData("findings")
  const { theme } = useTheme()

  const [allFindings, setAllFindings] = createSignal<Array<{ title: string; severity: number; confidence: number; description: string; tool: string }>>([])
  const [filterSev, setFilterSev] = createSignal<number | null>(null)
  const [loading, setLoading] = createSignal(true)

  const severityColor = (s: number) => s >= 4 ? theme.error : s >= 3 ? theme.warning : s >= 2 ? theme.primary : theme.textMuted
  const sevLabel = (s: number) => ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"][s] ?? "UNKNOWN"

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const all = store.listEngagements() as Array<{ id: string; target: string }>
      const engId = route.engagementId ?? (all.length > 0 ? all[all.length - 1].id : null)
      if (engId) {
        const findings = store.getFindings(engId) as Array<{ title: string; severity: number; confidence: number; description?: string; tool?: string }>
        setAllFindings(findings.map((f) => ({
          title: f.title, severity: f.severity ?? 0, confidence: f.confidence ?? 0,
          description: (f.description ?? "").slice(0, 200), tool: f.tool ?? "",
        })))
      }
      setLoading(false)
    } catch (e) { console.error("Failed to load findings:", e); setLoading(false) }
  })

  const filtered = createMemo(() => {
    const items = allFindings()
    return filterSev() !== null ? items.filter((f) => f.severity === filterSev()) : items
  })
  const counts = createMemo(() => ({
    critical: allFindings().filter((f) => f.severity >= 4).length,
    high: allFindings().filter((f) => f.severity === 3).length,
    medium: allFindings().filter((f) => f.severity === 2).length,
    low: allFindings().filter((f) => f.severity <= 1).length,
  }))

  return (
    <box flexDirection="column" paddingX={2} paddingTop={1} flexGrow={1}>
      <text fg={theme.text}>Findings</text>
      {/* Filter chips */}
      <box flexDirection="row" gap={1}>
        <text fg={filterSev() === null ? theme.primary : theme.textMuted}>All ({allFindings().length})</text>
        <text fg={filterSev() === 4 ? theme.error : theme.textMuted}>Critical ({counts().critical})</text>
        <text fg={filterSev() === 3 ? theme.warning : theme.textMuted}>High ({counts().high})</text>
        <text fg={filterSev() === 2 ? theme.primary : theme.textMuted}>Medium ({counts().medium})</text>
        <text fg={filterSev() === 1 ? theme.text : theme.textMuted}>Low ({counts().low})</text>
      </box>
      <Show when={!loading()}
        fallback={<text fg={theme.primary}>⠋ Loading...</text>}
      >
        <For each={filtered()}>
          {(finding) => (
            <box flexDirection="column">
              <box flexDirection="row" gap={1}>
                <text fg={severityColor(finding.severity)}>[{sevLabel(finding.severity)}]</text>
                <text fg={theme.text}>{finding.title}</text>
                <text fg={theme.textMuted}>({finding.tool})</text>
              </box>
              <Show when={finding.description}>
                <text fg={theme.textMuted}>{finding.description}</text>
              </Show>
            </box>
          )}
        </For>
        <Show when={filtered().length === 0 && !loading()}>
          <text fg={theme.textMuted}>No findings match the current filter.</text>
        </Show>
      </Show>
    </box>
  )
}
export default FindingsViewer
