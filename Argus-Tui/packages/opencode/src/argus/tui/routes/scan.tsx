/**
 * Scan Dashboard — Real-time assessment progress and results.
 *
 * Shows live phase progress, finding severity breakdown, and
 * a detailed finding list. Uses reactive ScanStore signals for
 * instant updates instead of SQLite polling.
 *
 * On mount, pre-populates ScanStore from SQLite for persistence
 * recovery (e.g. reconnecting to a running engagement).
 */
import { createMemo, createSignal, onMount, For, Show, onCleanup } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { Toast } from "@tui/ui/toast"
import { DropdownMenu } from "@tui/ui/dropdown-menu"
import { useRouteData } from "@tui/context/route"
import { getScanState, initScan, addPhase, completePhase, resetScan, setPlannerModel, appendLog } from "../scan-store"
import { responsiveBarWidth } from "../../shared/terminal"

const SPINNER_CHARS = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

function phaseIcon(status: string): string {
  switch (status) {
    case "COMPLETED": case "PASS": return "✓"
    case "RUNNING": return "⟳"
    case "FAILED": return "✗"
    case "PENDING": return "○"
    default: return "○"
  }
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const m = Math.floor(ms / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  return `${m}m ${s}s`
}

export function ScanDashboard() {
  const route = useRouteData("scan")
  const { theme } = useTheme()
  const [loading, setLoading] = createSignal(true)
  const [error, setError] = createSignal<string | null>(null)

  // Reactive reads from ScanStore — updates instantly on mutation
  const scanState = getScanState()

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const engagement = store.getEngagement(route.engagementId)
      if (!engagement) {
        setError("Engagement not found")
        setLoading(false)
        return
      }

      // Pre-populate ScanStore from SQLite for persistence recovery
      resetScan()
      initScan(engagement.target, engagement.id)

      const engPhases = store.getPhases(route.engagementId) as Array<{ id: string; name: string; status: string; error?: string }>
      const allFindings = store.getFindings(route.engagementId)
      const totalFindings = allFindings.length

      // Group findings by phase id for per-phase count display
      const findingsByPhase = new Map<string, number>()
      for (const f of allFindings) {
        const phaseKey = f.phase || "unknown"
        findingsByPhase.set(phaseKey, (findingsByPhase.get(phaseKey) ?? 0) + 1)
      }

      for (let i = 0; i < engPhases.length; i++) {
        const p = engPhases[i]
        addPhase({ id: p.id, name: p.name || p.id, index: i, total: engPhases.length })
        if (p.status === "COMPLETED" || p.status === "FAILED" || p.status === "PARTIAL") {
          const status = p.status === "PARTIAL" ? "partial" : p.status === "FAILED" ? "failed" : "completed"
          const phaseFindings = findingsByPhase.get(p.id) ?? 0
          completePhase(p.id, phaseFindings, p.error ? [p.error] : [], status)
        }
      }

      // Set scan status directly (total findings are accumulated per-phase via completePhase)
      // We intentionally do NOT call setTotalFindings(totalFindings) here because the per-phase
      // completePhase() calls above already add the per-phase counts to the total. Calling
      // setTotalFindings() on top would double-count findings from completed/partial phases on resume.
      const { completeScan } = await import("../scan-store")
      if (engagement.status === "COMPLETED" || engagement.status === "FAILED") {
        completeScan(engagement.status !== "FAILED")
      }

      setLoading(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load")
      setLoading(false)
    }
  })

  onCleanup(() => {
    // Don't reset on cleanup — keeps last state visible
  })

  const statusColor = (s: string) =>
    s === "COMPLETED" || s === "PASS" ? theme.success : s === "RUNNING" ? theme.primary : s === "FAILED" ? theme.error : theme.textMuted

  // Derived memos from reactive ScanStore
  const completedPhases = createMemo(() => scanState.phases.filter((p) => p.status === "completed").length)
  const totalPhases = createMemo(() => scanState.phases.length)
  const progressPct = createMemo(() => totalPhases() > 0 ? Math.round((completedPhases() / totalPhases()) * 100) : 0)

  // Animated spinner for running phases
  const [spinnerIdx, setSpinnerIdx] = createSignal(0)
  onMount(() => {
    const interval = setInterval(() => {
      setSpinnerIdx((prev) => (prev + 1) % SPINNER_CHARS.length)
    }, 120)
    onCleanup(() => clearInterval(interval))
  })
  const spinner = createMemo(() => SPINNER_CHARS[spinnerIdx()])

  // Available models for the model selector dropdown (lazy-loaded from LLMPlannerService)
  const [availableModels, setAvailableModels] = createSignal<string[]>([])
  const [modelsLoading, setModelsLoading] = createSignal(false)

  let modelsRefreshPromise: Promise<void> | null = null

  function refreshAvailableModels(): void {
    if (modelsLoading()) return
    setModelsLoading(true)
    modelsRefreshPromise = import("../../planner/llm-service")
      .then(({ LLMPlannerService }) => {
        setAvailableModels(LLMPlannerService.getAvailableModels())
      })
      .catch(() => {})
      .finally(() => {
        setModelsLoading(false)
        modelsRefreshPromise = null
      })
  }

  function selectModel(model: string): void {
    const refresh = modelsRefreshPromise ?? Promise.resolve()
    refresh.then(() => {
      import("../../planner/llm-service").then(({ LLMPlannerService }) => {
        LLMPlannerService.switchModel(model)
        setPlannerModel(
          `${model.includes("claude") ? "anthropic" : "openai"}/${model}`,
          `ARGUS_PLANNER_MODEL=${model}`,
        )
        appendLog(`🔁 Switched planner model to ${model}`)
      }).catch(() => {})
    })
  }

  // Progress bar characters
  const barWidth = createMemo(() => responsiveBarWidth())
  const filledBars = createMemo(() => Math.round((progressPct() / 100) * barWidth()))
  const emptyBars = createMemo(() => barWidth() - filledBars())
  const barFilled = createMemo(() => "█".repeat(filledBars()))
  const barEmpty = createMemo(() => "░".repeat(emptyBars()))

  // Running phase for highlighting
  const runningPhaseIndex = createMemo(() =>
    scanState.phases.findIndex((p) => p.status === "running")
  )

  return (
    <box flexDirection="column" paddingX={2} paddingTop={1} flexGrow={1}>
      {/* Header row: assessment title + model + status */}
      <box flexDirection="row" gap={1} paddingBottom={1}>
        <text fg={theme.text}><b>Assessment</b></text>
        <text fg={theme.textMuted}>{scanState.target || route.target}</text>
        {/* LLM model selector — dropdown with inline list of available models */}
        <Show when={scanState.llmPlanningModel && scanState.llmPlanningStatus === "completed"}>
          <DropdownMenu onOpenChange={(open: boolean) => { if (open) refreshAvailableModels() }}>
            <DropdownMenu.Trigger>
              <text fg={theme.textMuted}>{scanState.llmPlanningModel}</text>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content>
                <DropdownMenu.Group>
                  <DropdownMenu.GroupLabel>Planner Model (env: {scanState.llmPlanningModelConfig || scanState.llmPlanningModel})</DropdownMenu.GroupLabel>
                  <Show
                    when={!modelsLoading()}
                    fallback={<DropdownMenu.Item><DropdownMenu.ItemLabel>Loading...</DropdownMenu.ItemLabel></DropdownMenu.Item>}
                  >
                    <For each={availableModels()}>
                      {(model) => (
                        <DropdownMenu.RadioItem
                          value={model}
                          onSelect={() => selectModel(model)}
                        >
                          <DropdownMenu.ItemLabel>{model}</DropdownMenu.ItemLabel>
                        </DropdownMenu.RadioItem>
                      )}
                    </For>
                  </Show>
                </DropdownMenu.Group>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu>
        </Show>
        <Show when={scanState.status === "running"}>
          <text fg={theme.primary}>{spinner()} Running</text>
        </Show>
        <Show when={scanState.status === "completed"}>
          <text fg={theme.success}>✓ Complete</text>
        </Show>
        <Show when={scanState.status === "failed"}>
          <text fg={theme.error}>✗ Failed</text>
        </Show>
      </box>

      <Show when={!loading() && !error()} fallback={
        <Show when={loading()}><text fg={theme.primary}>⠋ Loading...</text></Show>
      }>
        {/* Progress bar */}
        <box flexDirection="row" gap={1} paddingBottom={1}>
          <text fg={theme.primary}>{barFilled()}</text>
          <text fg={theme.textMuted}>{barEmpty()}</text>
          <text fg={theme.text}>{progressPct()}%</text>
          <text fg={theme.textMuted}>({completedPhases()}/{totalPhases()} phases)</text>
          <Show when={scanState.durationMs > 0}>
            <text fg={theme.textMuted}>• {formatDuration(scanState.durationMs)}</text>
          </Show>
        </box>

        {/* Finding severity summary box */}
        <box
          borderStyle="rounded"
          border
          borderColor={theme.textMuted}
          paddingX={1}
          paddingY={1}
          marginBottom={1}
        >
          <box flexDirection="row" gap={2}>
            <box flexDirection="column" alignItems="center">
              <text fg={theme.error}><b>{scanState.totalFindings}</b></text>
              <text fg={theme.textMuted}>findings</text>
            </box>
          </box>
        </box>

        {/* Verification progress indicator */}
        <Show when={scanState.verificationTotal > 0}>
          <box flexDirection="row" gap={1} paddingBottom={1}>
            <Show
              when={scanState.verificationStatus === "completed"}
              fallback={
                <box flexDirection="row" gap={1}>
                  <text fg={theme.primary}>{spinner()}</text>
                  <text fg={theme.text}>Verifying findings: {scanState.verificationCurrent}/{scanState.verificationTotal}</text>
                </box>
              }
            >
              <box flexDirection="row" gap={1}>
                <Show when={scanState.verificationFailed === 0}>
                  <text fg={theme.success}>✓</text>
                </Show>
                <Show when={scanState.verificationFailed > 0}>
                  <text fg={theme.warning}>⚠</text>
                </Show>
                <text fg={theme.text}>
                  Verification complete: <text fg={theme.success}>{scanState.verificationPassed} passed</text>
                  <Show when={scanState.verificationFailed > 0}>
                    <text fg={theme.error}>, {scanState.verificationFailed} failed</text>
                  </Show>
                </text>
              </box>
            </Show>
          </box>
        </Show>

        {/* AI Analysis progress indicator */}
        <Show when={scanState.analysisTotal > 0}>
          <box flexDirection="row" gap={1} paddingBottom={1}>
            <Show
              when={scanState.analysisCurrent < scanState.analysisTotal}
              fallback={
                <text fg={theme.success}>✓ AI analysis complete ({scanState.analysisTotal} findings)</text>
              }
            >
              <text fg={theme.primary}>{spinner()} Analyzing findings: {scanState.analysisCurrent}/{scanState.analysisTotal}</text>
            </Show>
          </box>
        </Show>

        {/* ── LLM Planning Analysis ── */}
        <Show when={scanState.llmPlanningStatus !== "idle"}>
          <box
            borderStyle="rounded"
            border
            borderColor={scanState.llmPlanningStatus === "running" ? theme.primary : scanState.llmPlanningStatus === "failed" ? theme.error : theme.success}
            paddingX={1}
            paddingY={1}
            marginBottom={1}
          >
            <box flexDirection="column" gap={1}>
              <box flexDirection="row" gap={1}>
                <Show when={scanState.llmPlanningStatus === "running"}>
                  <text fg={theme.primary}>{spinner()} LLM Analysis</text>
                </Show>
                <Show when={scanState.llmPlanningStatus === "completed"}>
                  <text fg={theme.success}>✓ LLM Analysis</text>
                </Show>
                <Show when={scanState.llmPlanningStatus === "failed"}>
                  <text fg={theme.error}>✗ LLM Analysis failed</text>
                </Show>
                <Show when={scanState.llmPlanningSuggestions.length > 0}>
                  <text fg={theme.textMuted}>({scanState.llmPlanningSuggestions.length} suggestions)</text>
                </Show>
              </box>
              <Show when={scanState.llmPlanningTargetAnalysis && scanState.llmPlanningTargetAnalysis.length > 0}>
                <text fg={theme.textMuted}>{scanState.llmPlanningTargetAnalysis}</text>
              </Show>
              <Show when={scanState.llmPlanningError}>
                <text fg={theme.error}>{scanState.llmPlanningError}</text>
              </Show>
              <Show when={scanState.llmPlanningSuggestions.length > 0}>
                <For each={scanState.llmPlanningSuggestions}>
                  {(suggestion) => (
                    <box flexDirection="row" gap={1}>
                      <text fg={theme.primary}>→</text>
                      <text fg={theme.text}>{suggestion.capabilities.join(", ")}</text>
                    </box>
                  )}
                </For>
              </Show>
            </box>
          </box>
        </Show>

        {/* ── LLM Replan Analysis ── */}
        <Show when={scanState.llmReplanEntries.length > 0}>
          <box
            borderStyle="rounded"
            border
            borderColor={theme.warning}
            paddingX={1}
            paddingY={1}
            marginBottom={1}
          >
            <box flexDirection="column" gap={1}>
              <box flexDirection="row" gap={1}>
                <text fg={theme.warning}>⟳ LLM Replan</text>
                <text fg={theme.textMuted}>({scanState.llmReplanEntries.length} analysis)</text>
              </box>
              <For each={scanState.llmReplanEntries}>
                {(entry, idx) => (
                  <box flexDirection="column" gap={1}>
                    <Show when={entry.stopAssessment}>
                      <box flexDirection="row" gap={1}>
                        <text fg={theme.success}>■ Stop recommended</text>
                        <text fg={theme.textMuted}>{entry.reasoning}</text>
                      </box>
                    </Show>
                    <Show when={!entry.stopAssessment && entry.suggestedCapabilities.length > 0}>
                      <box flexDirection="row" gap={1}>
                        <text fg={theme.primary}>→ {entry.suggestedCapabilities.join(", ")}</text>
                        <text fg={theme.textMuted}>{entry.reasoning}</text>
                      </box>
                    </Show>
                  </box>
                )}
              </For>
            </box>
          </box>
        </Show>

        {/* Phase list with enhanced visualization */}
        <text fg={theme.textMuted} paddingBottom={1}>Workflow Phases</text>
        <For each={scanState.phases}>
          {(phase, idx) => {
            const isRunning = idx() === runningPhaseIndex()
            const statusUpper = phase.status.toUpperCase()
            return (
              <box
                flexDirection="column"
                paddingLeft={1}
                border={["left"]}
                borderColor={isRunning ? theme.primary : statusColor(statusUpper)}
              >
                <box flexDirection="row" gap={1}>
                  <text fg={isRunning ? theme.primary : statusColor(statusUpper)}>
                    {isRunning ? spinner() : phaseIcon(statusUpper)}
                  </text>
                  <text fg={theme.text}>{isRunning ? <b>{phase.name}</b> : phase.name}</text>
                  <Show when={isRunning}>
                    <text fg={theme.primary}>running</text>
                  </Show>
                  <Show when={phase.status === "completed"}>
                    <text fg={theme.success}>completed</text>
                    <Show when={phase.findings > 0}>
                      <text fg={theme.textMuted}>{phase.findings} finding(s)</text>
                    </Show>
                  </Show>
                  <Show when={phase.status === "failed"}>
                    <text fg={theme.error}>failed</text>
                  </Show>
                </box>
                <Show when={phase.errors.length > 0}>
                  <box flexDirection="row" gap={1} paddingLeft={3}>
                    <text fg={theme.error}>⚠ {phase.errors.join("; ")}</text>
                  </box>
                </Show>
              </box>
            )
          }}
        </For>

        {/* Log entries with timestamps */}
        <Show when={scanState.log.length > 0}>
          <text fg={theme.textMuted} paddingTop={1}>Activity Log</text>
          <For each={scanState.log.slice(-8)}>
            {(entry) => (
              <text fg={theme.textMuted}>{entry}</text>
            )}
          </For>
        </Show>
      </Show>

      {/* Error state */}
      <Show when={error() !== null}>
        <box flexDirection="row" gap={1}>
          <text fg={theme.error}>✗</text>
          <text fg={theme.text}>{error()}</text>
        </box>
      </Show>

      <box flexGrow={1} />
      <Toast />
    </box>
  )
}
export default ScanDashboard
