/**
 * Findings Viewer — Browse, filter, and inspect assessment findings.
 *
 * Shows findings with severity badges, confidence levels, evidence
 * counts, and tool attribution. Supports filtering by severity.
 */
import { createMemo, createSignal, onMount, For, Show } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { useRouteData } from "@tui/context/route"
import { navigateTo } from "@/argus/tui/navigator"

interface FindingRow {
  id: string
  title: string
  severity: number
  confidence: number
  description: string
  tool: string
  phase: string
  status: string
  cwe?: string
  owasp?: string
  remediation?: string
  createdAt: string
}

const SEV_LABELS = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
const CONF_LABELS = ["INFORMATIONAL", "LOW", "MEDIUM", "HIGH", "VERIFIED", "CONFIRMED"]

export function FindingCard(props: { finding: FindingRow; theme: ReturnType<typeof useTheme>["theme"] }) {
  const { finding, theme } = props
  const sevLabel = SEV_LABELS[finding.severity] ?? "UNKNOWN"
  const sevColor = finding.severity >= 4 ? theme.error : finding.severity >= 3 ? theme.warning : finding.severity >= 2 ? theme.info : theme.textMuted
  const confDots = "●".repeat(Math.min(finding.confidence, 5)) + "○".repeat(Math.max(5 - Math.min(finding.confidence, 5), 0))
  const confLabel = CONF_LABELS[finding.confidence] ?? "UNKNOWN"

  return (
    <box
      flexDirection="column"
      paddingX={1}
      paddingY={1}
      border={{ type: "round", fg: sevColor }}
      onClick={() => navigateTo({ type: "finding", findingId: finding.id })}
    >
      <box flexDirection="row" gap={1}>
        <text fg={sevColor} bold>[{sevLabel}]</text>
        <text fg={theme.text} bold>{finding.title}</text>
      </box>
      <text fg={theme.textMuted}>ID: {finding.id}</text>
      <box flexDirection="row" gap={1} paddingTop={1}>
        <text fg={theme.textMuted}>Confidence: {confDots} {confLabel}</text>
      </box>
      <box flexDirection="row" gap={1}>
        <text fg={theme.textMuted}>Tool: {finding.tool}</text>
        <Show when={finding.phase}>
          <text fg={theme.textMuted}>Phase: {finding.phase}</text>
        </Show>
      </box>
      <Show when={finding.cwe}>
        <box flexDirection="row" gap={1}>
          <text fg={theme.textMuted}>CWE: {finding.cwe}</text>
          <Show when={finding.owasp}>
            <text fg={theme.textMuted}>OWASP: {finding.owasp}</text>
          </Show>
        </box>
      </Show>
      <Show when={finding.description}>
        <text fg={theme.text} wrap="wrap" paddingTop={1}>
          {finding.description.slice(0, 200)}{finding.description.length > 200 ? "..." : ""}
        </text>
      </Show>
      <text fg={theme.primary}>Enter to view details</text>
    </box>
  )
}

export function FindingsViewer() {
  const route = useRouteData("findings")
  const { theme } = useTheme()

  const [allFindings, setAllFindings] = createSignal<FindingRow[]>([])
  const [filterSev, setFilterSev] = createSignal<number | null>(null)
  const [loading, setLoading] = createSignal(true)

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const all = store.listEngagements() as Array<{ id: string; target: string }>
      const engId = route.engagementId ?? (all.length > 0 ? all[all.length - 1].id : null)
      if (engId) {
        const findings = store.getFindings(engId)
        setAllFindings(findings.map((f) => ({
          id: f.id ?? "", title: f.title, severity: f.severity ?? 0,
          confidence: f.confidence ?? 0,
          description: (f.description ?? "").slice(0, 500),
          tool: f.tool ?? "", phase: f.phase ?? "",
          status: f.status ?? "PENDING",
          cwe: f.cwe, owasp: f.owasp, remediation: f.remediation,
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
          fg={filterSev() === 2 ? theme.info : theme.textMuted}
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
            {(finding) => <FindingCard finding={finding} theme={theme} />}
          </For>
        </Show>
      </Show>
    </box>
  )
}
export default FindingsViewer
