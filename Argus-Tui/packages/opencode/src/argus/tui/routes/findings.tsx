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
  evidenceCount?: number
}

const SEV_LABELS = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
const CONF_LABELS = ["INFORMATIONAL", "LOW", "MEDIUM", "HIGH", "VERIFIED", "CONFIRMED"]

const CONF_COLORS = ["#888", "#888", "#e8a838", "#5898e8", "#48b848", "#48b848"]

function confColor(confidence: number): string {
  const idx = Math.min(Math.max(confidence, 0), 5)
  return CONF_COLORS[idx]
}

function statusIcon(status: string): string {
  switch (status.toUpperCase()) {
    case "CONFIRMED": return "✓"
    case "REJECTED": return "✗"
    case "FINALIZED": return "🔒"
    case "PENDING": return "○"
    default: return "○"
  }
}

function statusColor(status: string, theme: ReturnType<typeof useTheme>["theme"]): string {
  switch (status.toUpperCase()) {
    case "CONFIRMED": return theme.success
    case "REJECTED": return theme.error
    case "FINALIZED": return theme.info
    default: return theme.textMuted
  }
}

export function FindingCard(props: { finding: FindingRow; theme: ReturnType<typeof useTheme>["theme"] }) {
  const { finding, theme } = props
  const sevLabel = SEV_LABELS[finding.severity] ?? "UNKNOWN"
  const sevColor = finding.severity >= 4 ? theme.error : finding.severity >= 3 ? theme.warning : finding.severity >= 2 ? theme.info : theme.textMuted

  // Colored confidence dots with gradient
  const confLevel = Math.min(finding.confidence, 5)
  const confLabel = CONF_LABELS[confLevel] ?? "UNKNOWN"

  return (
    <box
      flexDirection="column"
      paddingX={1}
      paddingY={1}
      border={{ type: "round", fg: sevColor }}
      onClick={() => navigateTo({ type: "finding", findingId: finding.id })}
    >
      {/* Header: severity badge + title + status */}
      <box flexDirection="row" gap={1}>
        <text fg={sevColor} bold>[{sevLabel}]</text>
        <text fg={theme.text} bold>{finding.title}</text>
        <Show when={finding.status !== "PENDING"}>
          <text fg={statusColor(finding.status, theme)}>{statusIcon(finding.status)} {finding.status.toLowerCase()}</text>
        </Show>
      </box>
      <text fg={theme.textMuted}>ID: {finding.id}</text>

      {/* Confidence with colored dots */}
      <box flexDirection="row" gap={1} paddingTop={1}>
        <text fg={theme.textMuted}>Confidence: </text>
        <For each={Array.from({ length: 5 }, (_, i) => i)}>
          {(i) => (
            <text fg={i < confLevel ? confColor(finding.confidence) : theme.textMuted}>
              {i < confLevel ? "●" : "○"}
            </text>
          )}
        </For>
        <text fg={confColor(finding.confidence)}>{confLabel}</text>
      </box>

      {/* Meta row: tool + phase + evidence count */}
      <box flexDirection="row" gap={1}>
        <text fg={theme.textMuted}>Tool: {finding.tool}</text>
        <Show when={finding.phase}>
          <text fg={theme.textMuted}>Phase: {finding.phase}</text>
        </Show>
        <Show when={finding.evidenceCount !== undefined && finding.evidenceCount > 0}>
          <text fg={theme.textMuted}>Evidence: {finding.evidenceCount} artifacts</text>
        </Show>
      </box>

      {/* CWE/OWASP */}
      <Show when={finding.cwe}>
        <box flexDirection="row" gap={1}>
          <text fg={theme.textMuted}>CWE: {finding.cwe}</text>
          <Show when={finding.owasp}>
            <text fg={theme.textMuted}>OWASP: {finding.owasp}</text>
          </Show>
        </box>
      </Show>

      {/* Description preview */}
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
        const rows: FindingRow[] = []
        for (const f of findings) {
          // Count evidence packages for each finding
          const packages = store.getEvidencePackages(f.id)
          let evidenceCount = 0
          for (const pkg of packages) {
            evidenceCount += store.getArtifacts(pkg.id).length
          }
          rows.push({
            id: f.id ?? "",
            title: f.title,
            severity: f.severity ?? 0,
            confidence: f.confidence ?? 0,
            description: (f.description ?? "").slice(0, 500),
            tool: f.tool ?? "",
            phase: f.phase ?? "",
            status: f.status ?? "PENDING",
            cwe: f.cwe,
            owasp: f.owasp,
            remediation: f.remediation,
            createdAt: f.created_at ?? "",
            evidenceCount,
          })
        }
        setAllFindings(rows)
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

  // Pagination
  const [page, setPage] = createSignal(1)
  const pageSize = 10
  const totalPages = createMemo(() => Math.max(1, Math.ceil(filtered().length / pageSize)))
  const pagedFindings = createMemo(() => {
    const items = filtered()
    const p = page()
    return items.slice((p - 1) * pageSize, p * pageSize)
  })



  return (
    <box flexDirection="column" paddingX={2} paddingTop={1} flexGrow={1}>
      <text fg={theme.text}>Findings</text>

      {/* Severity filter chips */}
      <box flexDirection="row" gap={1} paddingTop={1} flexWrap="wrap">
        <text
          fg={filterSev() === null ? theme.primary : theme.textMuted}
          onClick={() => { setFilterSev(null); setPage(1) }}
        >
          All ({allFindings().length})
        </text>
        <text
          fg={filterSev() === 4 ? theme.error : theme.textMuted}
          onClick={() => { setFilterSev(4); setPage(1) }}
        >
          Critical ({counts().critical})
        </text>
        <text
          fg={filterSev() === 3 ? theme.warning : theme.textMuted}
          onClick={() => { setFilterSev(3); setPage(1) }}
        >
          High ({counts().high})
        </text>
        <text
          fg={filterSev() === 2 ? theme.info : theme.textMuted}
          onClick={() => { setFilterSev(2); setPage(1) }}
        >
          Medium ({counts().medium})
        </text>
        <text
          fg={filterSev() === 1 ? theme.text : theme.textMuted}
          onClick={() => { setFilterSev(1); setPage(1) }}
        >
          Low ({counts().low})
        </text>
      </box>

      <Show when={!loading()} fallback={<text fg={theme.primary}>⠋ Loading...</text>}>
        <Show when={pagedFindings().length > 0} fallback={
          <box>
            <Show when={filterSev() === null}>
              <text fg={theme.textMuted} paddingTop={2}>No findings for this engagement.</text>
            </Show>
            <Show when={filterSev() !== null}>
              <text fg={theme.textMuted} paddingTop={2}>No findings match the current filter.</text>
            </Show>
          </box>
        }>
          <For each={pagedFindings()}>
            {(finding) => <FindingCard finding={finding} theme={theme} />}
          </For>
          {/* Pagination */}
          <Show when={totalPages() > 1}>
            <box flexDirection="row" gap={1} paddingTop={1} justifyContent="center">
              <Show when={page() > 1}>
                <text fg={theme.primary} onClick={() => setPage((p) => Math.max(1, p - 1))}>◀ Prev</text>
              </Show>
              <text fg={theme.textMuted}>Page {page()}/{totalPages()}</text>
              <Show when={page() < totalPages()}>
                <text fg={theme.primary} onClick={() => setPage((p) => Math.min(totalPages(), p + 1))}>Next ▶</text>
              </Show>
            </box>
          </Show>
        </Show>
      </Show>
    </box>
  )
}
export default FindingsViewer
