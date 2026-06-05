/**
 * Findings Viewer — Browse, filter, and inspect assessment findings.
 *
 * Shows findings with severity badges, confidence levels, evidence
 * counts, and tool attribution. Supports filtering by severity.
 */
import { createMemo, createSignal, onMount, For, Show } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { useRouteData, useRoute } from "@tui/context/route"

interface FindingRow {
  id: string
  title: string
  severity: number
  confidence: number
  description: string
  tool: string
  phase: string
  status: string
  createdAt: string
}

const SEV_LABELS = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
const CONF_LABELS = ["info", "low", "medium", "high", "verified", "confirmed"]

export function FindingsViewer() {
  const route = useRouteData("findings")
  const { theme } = useTheme()

  const [allFindings, setAllFindings] = createSignal<FindingRow[]>([])
  const [selected, setSelected] = createSignal<FindingRow | null>(null)
  const [filterSev, setFilterSev] = createSignal<number | null>(null)
  const [loading, setLoading] = createSignal(true)

  const severityColor = (s: number) =>
    s >= 4 ? theme.error : s >= 3 ? theme.warning : s >= 2 ? theme.primary : theme.textMuted

  const confidenceColor = (c: number) =>
    c >= 4 ? theme.success : c >= 3 ? theme.primary : c >= 2 ? theme.warning : theme.textMuted

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const all = store.listEngagements() as Array<{ id: string; target: string }>
      const engId = route.engagementId ?? (all.length > 0 ? all[all.length - 1].id : null)
      if (engId) {
        const findings = store.getFindings(engId) as Array<{
          id: string; title: string; severity: number; confidence: number;
          description?: string; tool?: string; phase?: string; status?: string; created_at?: string
        }>
        setAllFindings(findings.map((f) => ({
          id: f.id ?? "", title: f.title, severity: f.severity ?? 0,
          confidence: f.confidence ?? 0,
          description: (f.description ?? "").slice(0, 500),
          tool: f.tool ?? "", phase: f.phase ?? "",
          status: f.status ?? "PENDING",
          createdAt: f.created_at ?? "",
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
      <Show when={!selected()} fallback={
        /* Detail view for a single finding */
        <box flexDirection="column" flexGrow={1}>
          <box flexDirection="row" gap={1} paddingBottom={1}>
            <text
              fg={theme.primary}
              onClick={() => setSelected(null)}
            >
              ← Back
            </text>
          </box>
          <box flexDirection="row" gap={1}>
            <text
              fg={severityColor(selected()!.severity)}
              bold
            >
              [{SEV_LABELS[selected()!.severity]}]
            </text>
            <text fg={theme.text} bold>{selected()!.title}</text>
          </box>
          <box flexDirection="row" gap={2} paddingTop={1}>
            <text fg={theme.textMuted}>Confidence:</text>
            <text fg={confidenceColor(selected()!.confidence)}>
              {CONF_LABELS[selected()!.confidence] ?? "unknown"}
            </text>
            <text fg={theme.textMuted}>Tool:</text>
            <text fg={theme.text}>{selected()!.tool}</text>
            <text fg={theme.textMuted}>Status:</text>
            <text fg={theme.text}>{selected()!.status.toLowerCase()}</text>
          </box>
          <Show when={selected()!.phase}>
            <box flexDirection="row" gap={1}>
              <text fg={theme.textMuted}>Phase:</text>
              <text fg={theme.text}>{selected()!.phase}</text>
            </box>
          </Show>
          <Show when={selected()!.description}>
            <box flexDirection="column" paddingTop={1}>
              <text fg={theme.textMuted}>Description:</text>
              <text fg={theme.text}>{selected()!.description}</text>
            </box>
          </Show>
          <box flexGrow={1} />
        </box>
      }>
        {/* List view */}
        <text fg={theme.text}>Findings</text>

        {/* Severity filter chips */}
        <box flexDirection="row" gap={1} paddingTop={1}>
          <text
            fg={filterSev() === null ? theme.primary : theme.textMuted}
            onClick={() => setFilterSev(null)}
          >
            All ({allFindings().length})
          </text>
          <text
            fg={filterSev() === 4 ? theme.error : theme.textMuted}
            onClick={() => setFilterSev(4)}
          >
            Critical ({counts().critical})
          </text>
          <text
            fg={filterSev() === 3 ? theme.warning : theme.textMuted}
            onClick={() => setFilterSev(3)}
          >
            High ({counts().high})
          </text>
          <text
            fg={filterSev() === 2 ? theme.primary : theme.textMuted}
            onClick={() => setFilterSev(2)}
          >
            Medium ({counts().medium})
          </text>
          <text
            fg={filterSev() === 1 ? theme.text : theme.textMuted}
            onClick={() => setFilterSev(1)}
          >
            Low ({counts().low})
          </text>
        </box>

        <Show when={!loading()} fallback={<text fg={theme.primary}>⠋ Loading...</text>}>
          <Show when={filtered().length > 0} fallback={
            <text fg={theme.textMuted} paddingTop={2}>No findings match the current filter.</text>
          }>
            <For each={filtered()}>
              {(finding) => (
                <box
                  flexDirection="column"
                  paddingTop={1}
                  onClick={() => setSelected(finding)}
                >
                  {/* Finding header: severity badge + title + tool */}
                  <box flexDirection="row" gap={1}>
                    <text fg={severityColor(finding.severity)} bold>
                      [{SEV_LABELS[finding.severity]}]
                    </text>
                    <text fg={theme.text}>{finding.title}</text>
                    <text fg={theme.textMuted}>({finding.tool})</text>
                  </box>
                  {/* Finding metadata: confidence + phase + evidence */}
                  <box flexDirection="row" gap={2} paddingLeft={7}>
                    <text fg={confidenceColor(finding.confidence)}>
                      ● {CONF_LABELS[finding.confidence] ?? "unknown"}
                    </text>
                    <Show when={finding.phase}>
                      <text fg={theme.textMuted}>phase: {finding.phase}</text>
                    </Show>
                    <text fg={theme.textMuted}>{finding.status.toLowerCase()}</text>
                  </box>
                </box>
              )}
            </For>
          </Show>
        </Show>
      </Show>
    </box>
  )
}
export default FindingsViewer
