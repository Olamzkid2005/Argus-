import { createSignal, onMount, onCleanup, For, Show } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { useRoute } from "@tui/context/route"
import { Toast, useToast } from "@tui/ui/toast"

interface EngagementDetailProps {
  engagementId: string
  initialTab?: string
}

const SEV_LABELS = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
const CONF_LABELS = ["info", "low", "medium", "high", "verified", "confirmed"]

export function EngagementDetail(props: EngagementDetailProps) {
  const { theme } = useTheme()
  const route = useRoute()
  const [activeTab, setActiveTab] = createSignal(props.initialTab ?? "findings")
  const [engagement, setEngagement] = createSignal<{
    id: string; target: string; status: string; workflow: string; createdAt: string
  } | null>(null)
  const [findings, setFindings] = createSignal<Array<{
    id: string; title: string; severity: number; confidence: number; tool: string; status: string; description: string
  }>>([])
  const [evidence, setEvidence] = createSignal<Array<{
    findingId: string; findingTitle: string
    packages: Array<{ id: string; packageHash: string; createdAt: number; artifacts: Array<{ id: string; path: string; type: string }> }>
  }>>([])
  const [timeline, setTimeline] = createSignal<Array<{
    id: string; eventType: string; message: string; createdAt: number
  }>>([])
  const [eventFilter, setEventFilter] = createSignal<"all" | "phase" | "tool" | "error">("all")
  const [loading, setLoading] = createSignal(true)

  // Map event types to filter categories — "all" shows everything
  const eventCategory = (eventType: string): "phase" | "tool" | "error" => {
    if (/^(PHASE|REPLAN|RESUME)/.test(eventType)) return "phase"
    if (/^(CREDS|EVIDENCE)/.test(eventType)) return "tool"
    return "error"  // RUNNER_ERROR, RESUME_ERROR, or anything else
  }

  // Derive filtered timeline reactively
  const filteredTimeline = () => {
    const f = eventFilter()
    if (f === "all") return timeline()
    return timeline().filter((e) => eventCategory(e.eventType) === f)
  }
  const toast = useToast()

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      onCleanup(() => store.close())
      const detail = store.getEngagementDetail(props.engagementId)
      if (detail) {
        setEngagement({
          id: detail.engagement.id, target: detail.engagement.target,
          status: detail.engagement.status,
          workflow: detail.engagement.workflow, createdAt: detail.engagement.createdAt,
        })
        setFindings(detail.findings.map((f) => ({
          id: f.id, title: f.title, severity: f.severity, confidence: f.confidence,
          tool: f.tool ?? "", status: f.status, description: f.description ?? "",
        })))
        setEvidence(detail.evidence)
        setTimeline(detail.auditLog)
      }
      setLoading(false)
    } catch (e) {
      toast.error(e)
      setLoading(false)
    }
  })

  const tabs = [
    { id: "findings", label: "Findings" },
    { id: "evidence", label: "Evidence" },
    { id: "timeline", label: "Timeline" },
    { id: "reports", label: "Reports" },
  ]

  const severityColor = (s: number) =>
    s >= 4 ? theme.error : s >= 3 ? theme.warning : s >= 2 ? theme.primary : theme.textMuted

  const confidenceColor = (c: number) =>
    c >= 4 ? theme.success : c >= 3 ? theme.primary : c >= 2 ? theme.warning : theme.textMuted

  return (
    <box flexDirection="column" paddingX={2} paddingTop={1} flexGrow={1}>
      <Show when={engagement()} fallback={
        <Show when={!loading()} fallback={
          <SkeletonLoading theme={theme} />
        }>
          <text fg={theme.error}>Engagement {props.engagementId} not found.</text>
        </Show>
      }>
        {(eng) => (
          <>
            <text fg={theme.text}><b>{eng().id}</b></text>
            <text fg={theme.textMuted}>Target: {eng().target}</text>
            <text fg={theme.textMuted}>Status: {eng().status.toLowerCase()}</text>

            {/* Tab bar */}
            <box flexDirection="row" gap={1} paddingTop={2}>
              <For each={tabs}>
                {(tab) => (
                  <box {...({ onClick: () => {
                    setActiveTab(tab.id)
                    route.navigate({ type: "engagement-detail", engagementId: props.engagementId, tab: tab.id })
                  } } as any)}>
                    <text fg={activeTab() === tab.id ? theme.primary : theme.textMuted}>
                      {activeTab() === tab.id ? <b>{tab.label}</b> : tab.label}
                    </text>
                  </box>
                )}
              </For>
            </box>

            {/* Tab content */}
            <box paddingTop={1} flexGrow={1}>
              {/* Findings tab */}
              <Show when={activeTab() === "findings"}>
                <Show when={findings().length > 0} fallback={
                  <text fg={theme.textMuted}>No findings for this engagement.</text>
                }>
                  <For each={findings()}>
                    {(f) => (
                      <box flexDirection="column" paddingTop={1}>
                        <box flexDirection="row" gap={1}>
                          <text fg={severityColor(f.severity)}>
                            <b>[{SEV_LABELS[f.severity]}]</b>
                          </text>
                          <text fg={theme.text}>{f.title}</text>
                          <text fg={theme.textMuted}>({f.tool})</text>
                        </box>
                        <box flexDirection="row" gap={2} paddingLeft={7}>
                          <text fg={confidenceColor(f.confidence)}>
                            ● {CONF_LABELS[f.confidence]}
                          </text>
                          <text fg={theme.textMuted}>{f.status.toLowerCase()}</text>
                        </box>
                      </box>
                    )}
                  </For>
                </Show>
              </Show>

              {/* Evidence tab */}
              <Show when={activeTab() === "evidence"}>
                <Show when={evidence().length > 0} fallback={
                  <text fg={theme.textMuted}>No evidence captured yet.</text>
                }>
                  <For each={evidence()}>
                    {(ev) => (
                      <box flexDirection="column" paddingTop={1}>
                        <text fg={theme.text}><b>{ev.findingTitle}</b></text>
                        <text fg={theme.textMuted}>{ev.packages.length} evidence package(s)</text>
                        <For each={ev.packages}>
                          {(pkg) => (
                            <box flexDirection="column" paddingLeft={2}>
                              <text fg={theme.textMuted}>
                                Package {pkg.id} — {pkg.artifacts.length} artifact(s)
                              </text>
                            </box>
                          )}
                        </For>
                      </box>
                    )}
                  </For>
                </Show>
              </Show>

              {/* Timeline tab */}
              <Show when={activeTab() === "timeline"}>
                {/* Filter bar */}
                <box flexDirection="row" gap={2} paddingBottom={1}>
                  <For each={["all", "phase", "tool", "error"] as const}>
                    {(f) => (
                      <box {...({ onClick: () => setEventFilter(f) } as any)}>
                        <text fg={eventFilter() === f ? theme.primary : theme.textMuted}>
                          {eventFilter() === f ? <b>[{f}]</b> : `[${f}]`}
                        </text>
                      </box>
                    )}
                  </For>
                </box>
                <Show when={filteredTimeline().length > 0} fallback={
                  <text fg={theme.textMuted}>No timeline events recorded.</text>
                }>
                  <For each={filteredTimeline()}>
                    {(evt) => (
                      <box flexDirection="row" gap={1} paddingTop={1}>
                        <text fg={theme.textMuted}>
                          {new Date(evt.createdAt).toLocaleString()}
                        </text>
                        <text fg={theme.text}>{evt.message}</text>
                      </box>
                    )}
                  </For>
                </Show>
              </Show>

              {/* Reports tab */}
              <Show when={activeTab() === "reports"}>
                <box flexDirection="column" gap={1}>
                  <text fg={theme.textMuted}>Report status: Not generated</text>
                  <box {...({ onClick: () => {
                    route.navigate({ type: "report", engagementId: props.engagementId })
                  } } as any)}>
                    <text fg={theme.primary}>Generate report →</text>
                  </box>
                </box>
              </Show>
            </box>
          </>
        )}
      </Show>
      <box flexGrow={1} />
      <Toast />
    </box>
  )
}

/**
 * Structural skeleton loading that matches the engagement detail page layout.
 * Uses block characters (▓/░) in the muted text color to show the page structure
 * while data is loading — header bars, tab row, and 5 finding list placeholders.
 */
function SkeletonLoading(props: { theme: ReturnType<typeof useTheme>["theme"] }) {
  const { theme } = props
  return (
    <box flexDirection="column" padding={1}>
      <text fg={theme.primary}>⠋ Loading engagement...</text>
      <text fg={theme.textMuted}>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</text>
      <text fg={theme.textMuted}>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</text>
      <box flexDirection="row" gap={2} paddingTop={1} paddingBottom={1}>
        <text fg={theme.textMuted}>▓▓▓▓▓▓▓▓▓</text>
        <text fg={theme.textMuted}>▓▓▓▓▓▓▓▓▓▓▓</text>
        <text fg={theme.textMuted}>▓▓▓▓▓▓▓▓▓▓</text>
        <text fg={theme.textMuted}>▓▓▓▓▓▓▓▓</text>
      </box>
      <For each={[1, 2, 3, 4, 5]}>
        {() => (
          <box flexDirection="column" paddingTop={1}>
            <text fg={theme.textMuted}>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</text>
            <text fg={theme.textMuted}>▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓</text>
          </box>
        )}
      </For>
    </box>
  )
}

export default EngagementDetail
