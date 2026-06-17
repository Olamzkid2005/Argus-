import { createSignal, onMount, For, Show } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { useRoute } from "@tui/context/route"

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
  const [loading, setLoading] = createSignal(true)

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const eng = store.getEngagement(props.engagementId)
      if (eng) {
        setEngagement({
          id: eng.id, target: eng.target, status: eng.status,
          workflow: eng.workflow, createdAt: eng.createdAt,
        })
        const rawFindings = store.getFindings(props.engagementId)
        setFindings(rawFindings.map((f) => ({
          id: f.id, title: f.title, severity: f.severity, confidence: f.confidence,
          tool: f.tool ?? "", status: f.status, description: f.description ?? "",
        })))
        const rawEvidence = store.getEvidenceByEngagement(props.engagementId)
        setEvidence(rawEvidence)
        const rawTimeline = store.getAuditLog(props.engagementId)
        setTimeline(rawTimeline)
      }
      setLoading(false)
    } catch {
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
        <Show when={!loading()} fallback={<text fg={theme.primary}>⠋ Loading...</text>}>
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
                    route.navigate({ type: "engagement", engagementId: props.engagementId, tab: tab.id })
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
                <Show when={timeline().length > 0} fallback={
                  <text fg={theme.textMuted}>No timeline events recorded.</text>
                }>
                  <For each={timeline()}>
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
    </box>
  )
}

export default EngagementDetail
