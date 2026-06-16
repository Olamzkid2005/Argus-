/**
 * FindingDetail — Full-screen detail view for a single finding.
 */
import { createSignal, onMount, Show, For } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { EvidenceViewer } from "./evidence-viewer"
import { Feature, getFeatureFlags } from "@/argus/config/feature-flags"
import type { NormalizedFinding, FindingAnalysis } from "@/argus/shared/types"

const SEV_LABELS = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
const CONF_LABELS = ["INFORMATIONAL", "LOW", "MEDIUM", "HIGH", "VERIFIED", "CONFIRMED"]

interface FindingDetailProps {
  findingId: string
}

export function FindingDetail(props: FindingDetailProps) {
  const { theme } = useTheme()
  const [finding, setFinding] = createSignal<NormalizedFinding | null>(null)
  const [evidenceCount, setEvidenceCount] = createSignal(0)
  const [loading, setLoading] = createSignal(true)
  const [analysis, setAnalysis] = createSignal<FindingAnalysis | null>(null)
  const [analysisLoading, setAnalysisLoading] = createSignal(false)
  const [analysisError, setAnalysisError] = createSignal<string | null>(null)

  const sevColor = (s: number) =>
    s >= 4 ? theme.error : s >= 3 ? theme.warning : s >= 2 ? theme.info : theme.textMuted

  const llmEnabled = () => getFeatureFlags().isEnabled(Feature.LLM_FINDING_ANALYSIS)

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const found = store.getFinding(props.findingId)
      if (found) {
        setFinding(found)
        const packages = store.getEvidencePackages(found.id)
        let count = 0
        for (const pkg of packages) {
          const artifacts = store.getArtifacts(pkg.id)
          count += artifacts.length
        }
        setEvidenceCount(count)
      }
      setLoading(false)
      if (llmEnabled()) {
        try {
          const cached = store.getValidAnalysis(props.findingId)
          if (cached) setAnalysis(cached)
        } catch { /* no analysis yet */ }
      }
    } catch {
      setLoading(false)
    }
  })

  const generateAnalysis = async () => {
    setAnalysisLoading(true)
    setAnalysisError(null)
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const f = finding()
      if (!f) return
            const { FindingAnalyzer } = await import("@/argus/engagement/finding-analyzer")
      const analyzer = new FindingAnalyzer(store)
      const result = await analyzer.analyze(f, [])
      if (!result) { setAnalysisError("LLM client not configured"); return }


      setAnalysis(result)
    } catch (error) {
      setAnalysisError("Analysis failed: " + (error instanceof Error ? error.message : "Unknown error"))
    } finally {
      setAnalysisLoading(false)
    }
  }

  return (
    <box flexDirection="column" paddingX={2} paddingTop={1} flexGrow={1}>
      <Show when={finding()} fallback={
        <Show when={!loading()} fallback={<text fg={theme.primary}>Loading...</text>}>
          <text fg={theme.error}>Finding not found: {props.findingId}</text>
        </Show>
      }>
        {(f) => (
          <>
            {/* Header */}
            <box flexDirection="row" gap={1}>
              <text fg={sevColor(f().severity)}><b>[{SEV_LABELS[f().severity] ?? "UNKNOWN"}]</b></text>
              <text fg={theme.text}><b>{f().title}</b></text>
            </box>
            <text fg={theme.textMuted}>ID: {f().id}</text>
            <text fg={theme.textMuted}>Status: {CONF_LABELS[f().confidence] ?? "UNKNOWN"}</text>

            {/* Details section */}
            <box flexDirection="column" paddingTop={1} border={["bottom"]} borderColor={theme.textMuted}>
              <text fg={theme.text}><b>Details</b></text>
              <box flexDirection="row" gap={2} paddingTop={1}>
                <text fg={theme.textMuted}>Tool: {f().tool}</text>
                <text fg={theme.textMuted}>Phase: {f().phase}</text>
                <text fg={theme.textMuted}>Evidence: {evidenceCount()} artifacts</text>
              </box>
              <box flexDirection="row" gap={2}>
                <Show when={f().cwe}>
                  <text fg={theme.textMuted}>CWE: {f().cwe}</text>
                </Show>
                <Show when={f().owasp}>
                  <text fg={theme.textMuted}>OWASP: {f().owasp}</text>
                </Show>
              </box>
            </box>

            {/* Description */}
            <Show when={f().description}>
              <box flexDirection="column" paddingTop={1}>
                <text fg={theme.text}><b>Description</b></text>
                <text fg={theme.text} paddingTop={1}>{f().description}</text>
              </box>
            </Show>

            {/* Remediation */}
            <Show when={f().remediation}>
              <box flexDirection="column" paddingTop={1}>
                <text fg={theme.text}><b>Remediation</b></text>
                <text fg={theme.text} paddingTop={1}>{f().remediation}</text>
              </box>
            </Show>

            {/* AI Analysis */}
            <box flexDirection="column" paddingTop={1} border={["bottom"]} borderColor={theme.textMuted}>
              <text fg={theme.text}><b>AI Analysis</b></text>
              <Show when={analysis()} fallback={
                <Show when={!analysisLoading()} fallback={
                  <text fg={theme.primary}>⠋ Generating AI analysis...</text>
                }>
                  <Show when={analysisError()} fallback={
                    <Show when={llmEnabled()} fallback={
                      <text fg={theme.textMuted} paddingTop={1}>
                        LLM analysis disabled. Enable with `features.llm_finding_analysis: true` in config.
                      </text>
                    }>
                      <box {...({ onClick: generateAnalysis } as any)} paddingTop={1}>
                        <text fg={theme.primary}>[Generate AI Analysis]</text>
                      </box>
                    </Show>
                  }>
                    <text fg={theme.error} paddingTop={1}>{analysisError()}</text>
                  </Show>
                </Show>
              }>
                {(a) => (
                  <>
                    <text fg={theme.text} paddingTop={1}>{a().explanation}</text>
                    <Show when={a().impact?.length > 0}>
                      <text fg={theme.warning} paddingTop={1}><b>Impact:</b></text>
                      <For each={a().impact}>
                        {(item: string) => (
                          <box flexDirection="row" gap={1}>
                            <text fg={theme.warning}>•</text>
                            <text fg={theme.text}>{item}</text>
                          </box>
                        )}
                      </For>
                    </Show>
                    <Show when={a().remediation?.length > 0}>
                      <text fg={theme.success} paddingTop={1}><b>Remediation:</b></text>
                      <For each={a().remediation}>
                        {(item: string) => (
                          <box flexDirection="row" gap={1}>
                            <text fg={theme.success}>•</text>
                            <text fg={theme.text}>{item}</text>
                          </box>
                        )}
                      </For>
                    </Show>
                    <box flexDirection="row" gap={1} paddingTop={1}>
                      <text fg={theme.textMuted}>Generated by: {a().model}</text>
                      <box {...({ onClick: generateAnalysis } as any)}><text fg={theme.primary}>[Regenerate]</text></box>
                    </box>
                  </>
                )}
              </Show>
            </box>

            {/* Evidence */}
            <box flexDirection="column" paddingTop={1}>
              <text fg={theme.text}><b>Evidence ({evidenceCount()} artifacts)</b></text>
              <EvidenceViewer findingId={f().id} />
            </box>
          </>
        )}
      </Show>
    </box>
  )
}
export default FindingDetail
