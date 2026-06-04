/**
 * Findings Viewer — Browse and filter assessment findings.
 */

import { createEffect, createMemo, createSignal, onMount, For, Show } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { useRouteData } from "@tui/context/route"
import { Toast } from "@tui/ui/toast"

interface FindingItem {
  title: string
  severity: number
  confidence: number
  description: string
  tool: string
  phase: string
  status: string
}

export function FindingsViewer() {
  const route = useRouteData("findings")
  const { theme } = useTheme()

  const [allFindings, setAllFindings] = createSignal<FindingItem[]>([])
  const [engagements, setEngagements] = createSignal<Array<{ id: string; target: string }>>([])
  const [selectedEng, setSelectedEng] = createSignal<string | null>(route.engagementId ?? null)
  const [filterSev, setFilterSev] = createSignal<number | null>(null)
  const [loading, setLoading] = createSignal(true)

  const severityLabel = (s: number) => ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"][s] ?? "UNKNOWN"
  const severityColor = (s: number) => {
    if (s >= 4) return "#ef4444"
    if (s >= 3) return "#f59e0b"
    if (s >= 2) return "#00bcd4"
    return theme.textMuted
  }

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const all = store.listEngagements()
      setEngagements(all.map((e: any) => ({ id: e.id, target: e.target })))

      if (!selectedEng() && all.length > 0) {
        setSelectedEng(all[all.length - 1].id)
      }

      if (selectedEng()) {
        const findings = store.getFindings(selectedEng()!)
        setAllFindings(findings.map((f: any) => ({
          title: f.title,
          severity: f.severity ?? 0,
          confidence: f.confidence ?? 0,
          description: (f.description ?? "").slice(0, 200),
          tool: f.tool ?? "",
          phase: f.phase ?? "",
          status: f.status ?? "PENDING",
        })))
      }
      setLoading(false)
    } catch (e) {
      setLoading(false)
    }
  })

  const filtered = createMemo(() => {
    let items = allFindings()
    if (filterSev() !== null) {
      items = items.filter((f) => f.severity === filterSev())
    }
    return items
  })

  const critical = createMemo(() => allFindings().filter((f) => f.severity >= 4).length)
  const high = createMemo(() => allFindings().filter((f) => f.severity === 3).length)
  const medium = createMemo(() => allFindings().filter((f) => f.severity === 2).length)
  const low = createMemo(() => allFindings().filter((f) => f.severity <= 1).length)

  return (
    <box flexDirection="column" paddingX={2} paddingTop={1} flexGrow={1}>
      {/* Header */}
      <box flexDirection="row" gap={1} paddingBottom={1}>
        <text fg={theme.text} font="mono" attributes={{ bold: true }}>Findings</text>
        <Show when={selectedEng()}>
          <text fg={theme.textMuted} font="mono">{selectedEng()}</text>
        </Show>
      </box>

      {/* Severity filter chips */}
      <box flexDirection="row" gap={1} paddingY={0.5}>
        <box
          paddingX={0.5}
          onMouse={(e: any) => { if (e.type === "down") setFilterSev(null) }}
        >
          <text fg={filterSev() === null ? (theme.primary as any) : theme.textMuted} font="mono">
            All ({allFindings().length})
          </text>
        </box>
        <box
          paddingX={0.5}
          onMouse={(e: any) => { if (e.type === "down") setFilterSev(4) }}
        >
          <text fg={filterSev() === 4 ? "#ef4444" : theme.textMuted} font="mono">
            Critical ({critical()})
          </text>
        </box>
        <box
          paddingX={0.5}
          onMouse={(e: any) => { if (e.type === "down") setFilterSev(3) }}
        >
          <text fg={filterSev() === 3 ? "#f59e0b" : theme.textMuted} font="mono">
            High ({high()})
          </text>
        </box>
        <box
          paddingX={0.5}
          onMouse={(e: any) => { if (e.type === "down") setFilterSev(2) }}
        >
          <text fg={filterSev() === 2 ? "#00bcd4" : theme.textMuted} font="mono">
            Medium ({medium()})
          </text>
        </box>
        <box
          paddingX={0.5}
          onMouse={(e: any) => { if (e.type === "down") setFilterSev(1) }}
        >
          <text fg={filterSev() === 1 ? theme.text : theme.textMuted} font="mono">
            Low ({low()})
          </text>
        </box>
      </box>

      {/* Findings list */}
      <Show when={!loading()}>
        <For each={filtered()}>
          {(finding) => (
            <box flexDirection="column" paddingY={0.3}>
              <box flexDirection="row" gap={1}>
                <text fg={severityColor(finding.severity) as any} font="mono" attributes={{ bold: true }}>
                  [{severityLabel(finding.severity)}]
                </text>
                <text fg={theme.text} font="mono">{finding.title}</text>
                <text fg={theme.textMuted} font="mono">({finding.tool})</text>
              </box>
              <Show when={finding.description}>
                <box paddingLeft={2}>
                  <text fg={theme.textMuted} font="mono" size="small">
                    {finding.description}
                  </text>
                </box>
              </Show>
            </box>
          )}
        </For>
        <Show when={filtered().length === 0 && !loading()}>
          <text fg={theme.textMuted} font="mono" paddingTop={1}>No findings match the current filter.</text>
        </Show>
      </Show>

      <Show when={loading()}>
        <text fg={theme.textMuted} font="mono" paddingTop={1}>Loading findings...</text>
      </Show>

      <box flexGrow={1} />
      <Toast />
    </box>
  )
}

export default FindingsViewer
