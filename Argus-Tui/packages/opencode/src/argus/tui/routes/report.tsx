/**
 * Report Dashboard — Generate and view assessment reports.
 *
 * Loads an engagement and its findings from the EngagementStore,
 * generates a markdown report via ReportGenerator, and displays
 * the rendered report in a scrollable terminal viewer.
 */

import { createSignal, onMount, For, Show } from "solid-js"
import { useTheme } from "@tui/context/theme"
import { Toast } from "@tui/ui/toast"

interface ReportDashboardProps {
  engagementId: string
}

export function ReportDashboard(props: ReportDashboardProps) {
  const { theme } = useTheme()

  const [loading, setLoading] = createSignal(true)
  const [error, setError] = createSignal<string | null>(null)
  const [reportContent, setReportContent] = createSignal<string>("")
  const [engagementInfo, setEngagementInfo] = createSignal<{
    target: string
    workflow: string
    status: string
    createdAt: string
    totalFindings: number
  } | null>(null)

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()

      const engagement = store.getEngagement(props.engagementId)
      if (!engagement) {
        setError(`Engagement not found: ${props.engagementId}`)
        setLoading(false)
        return
      }

      const findings = store.getFindings(props.engagementId)
      const phases = store.getPhases(props.engagementId)

      setEngagementInfo({
        target: engagement.target,
        workflow: engagement.workflow,
        status: engagement.status,
        createdAt: engagement.createdAt,
        totalFindings: findings.length,
      })

      // Generate the markdown report
      const { ReportGenerator } = await import("@/argus/reporting/generator")
      const generator = new ReportGenerator()
      const markdown = generator.generateMarkdown(
        findings,
        engagement.id,
        engagement.target,
        engagement.workflow,
      )

      // Prepend phase summary to the report
      const phaseSummary = phases
        .map((p) => `- ${p.name}: ${p.status}`)
        .join("\n")
      const header = [
        `# Security Assessment Report: ${engagement.target}`,
        `**Engagement:** ${engagement.id}`,
        `**Workflow:** ${engagement.workflow}`,
        `**Status:** ${engagement.status}`,
        `**Date:** ${new Date().toISOString()}`,
        "",
        "## Phase Summary",
        phaseSummary || "  No phases recorded",
        "",
      ].join("\n")

      setReportContent(header + markdown.replace(/^# .+\n/m, ""))
      setLoading(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate report")
      setLoading(false)
    }
  })

  return (
    <box flexDirection="column" paddingX={2} paddingTop={1} flexGrow={1}>
      {/* Header */}
      <box flexDirection="row" gap={1} paddingBottom={1}>
        <text fg={theme.text}>Report</text>
        <Show when={engagementInfo()}>
          <text fg={theme.textMuted}>{engagementInfo()!.target}</text>
          <text fg={theme.textMuted}>•</text>
          <text fg={theme.textMuted}>{engagementInfo()!.totalFindings} findings</text>
          <Show when={engagementInfo()!.status === "COMPLETED"}>
            <text fg={theme.success}>✓ Complete</text>
          </Show>
          <Show when={engagementInfo()!.status === "FAILED"}>
            <text fg={theme.error}>✗ Failed</text>
          </Show>
          <Show when={engagementInfo()!.status === "RUNNING"}>
            <text fg={theme.primary}>⟳ Running</text>
          </Show>
        </Show>
      </box>

      {/* Loading state */}
      <Show when={loading()}>
        <box flexDirection="row" gap={1}>
          <text fg={theme.primary}>⠋ Generating report...</text>
        </box>
      </Show>

      {/* Error state */}
      <Show when={error() !== null && !loading()}>
        <box
          flexDirection="column"
          paddingX={1}
          paddingY={1}
          border={["left"]}
          borderColor={theme.error}
        >
          <box flexDirection="row" gap={1}>
            <text fg={theme.error}>✗</text>
            <text fg={theme.text}>{error()}</text>
          </box>
        </box>
      </Show>

      {/* Report content in a scrollable viewer */}
      <Show when={!loading() && !error() && reportContent()}>
        <scrollbox
          flexGrow={1}
          minHeight={0}
          verticalScrollbarOptions={{
            paddingLeft: 1,
            visible: true,
            trackOptions: {
              backgroundColor: theme.backgroundElement,
              foregroundColor: theme.border,
            },
          }}
        >
          <box flexDirection="column" paddingBottom={1} gap={0}>
            {/* Report header */}
            <Show when={engagementInfo()}>
              <box
                flexDirection="row"
                gap={2}
                paddingY={1}
                paddingX={1}
                border={["round"]}
                borderColor={theme.border}
                marginBottom={1}
              >
                <box flexDirection="column">
                  <text fg={theme.text}><b>Target</b></text>
                  <text fg={theme.textMuted}>{engagementInfo()!.target}</text>
                </box>
                <box flexDirection="column">
                  <text fg={theme.text}><b>Workflow</b></text>
                  <text fg={theme.textMuted}>{engagementInfo()!.workflow}</text>
                </box>
                <box flexDirection="column">
                  <text fg={theme.text}><b>Status</b></text>
                  <text fg={theme.textMuted}>{engagementInfo()!.status}</text>
                </box>
                <box flexDirection="column">
                  <text fg={theme.text}><b>Findings</b></text>
                  <text fg={theme.textMuted}>{engagementInfo()!.totalFindings}</text>
                </box>
              </box>
            </Show>

            {/* Report body */}
            <box flexDirection="column" gap={0}>
              <For each={reportContent().split("\n")}>
                {(line) => {
                  if (line.startsWith("### ")) {
                    return (
                      <box flexDirection="row" gap={1} paddingTop={1}>
                        <text fg={theme.text}><b>{line.replace("### ", "")}</b></text>
                      </box>
                    )
                  }
                  if (line.startsWith("## ")) {
                    return (
                      <box flexDirection="row" gap={1} paddingTop={1} paddingBottom={1}>
                        <box
                          border={["left"]}
                          borderColor={theme.primary}
                          paddingLeft={1}
                        >
                          <text fg={theme.primary}><b>{line.replace("## ", "")}</b></text>
                        </box>
                      </box>
                    )
                  }
                  if (line.startsWith("- **")) {
                    return (
                      <box flexDirection="row" gap={1} paddingLeft={2}>
                        <text fg={theme.textMuted}>•</text>
                        <text fg={theme.text}>{line.replace(/^-\s\*\*(.+?)\*\*:\s*/, "").trim()}</text>
                        <text fg={theme.textMuted}>
                          {line.match(/^\-\s\*\*(.+?)\*\*/)?.[1] ? `[${line.match(/^\-\s\*\*(.+?)\*\*/)![1]}]` : ""}
                        </text>
                      </box>
                    )
                  }
                  if (line.startsWith("  - ")) {
                    return (
                      <box flexDirection="row" gap={1} paddingLeft={4}>
                        <text fg={theme.textMuted}>-</text>
                        <text fg={theme.text}>{line.replace(/^\s+-\s+/, "")}</text>
                      </box>
                    )
                  }
                  if (line.startsWith("### 🔍")) {
                    return (
                      <box flexDirection="row" gap={1} paddingTop={1}>
                        <text fg={theme.info}><b>🔍 AI Analysis</b></text>
                      </box>
                    )
                  }
                  if (line.startsWith("*Generated by:")) {
                    return (
                      <text fg={theme.textMuted} paddingTop={1}>
                        {line}
                      </text>
                    )
                  }
                  if (line.startsWith("**")) {
                    return (
                      <box flexDirection="row" gap={1} paddingTop={1}>
                        <text fg={theme.text}>{line}</text>
                      </box>
                    )
                  }
                  if (!line.trim()) return <text>&nbsp;</text>
                  return (
                    <box flexDirection="row" gap={1}>
                      <text fg={theme.text}>{line}</text>
                    </box>
                  )
                }}
              </For>
            </box>
          </box>
        </scrollbox>
      </Show>

      {/* Empty state when no content */}
      <Show when={!loading() && !error() && !reportContent()}>
        <box flexDirection="column" paddingTop={2}>
          <text fg={theme.textMuted}>No report content available.</text>
        </box>
      </Show>

      <box flexGrow={1} />
      <Toast />
    </box>
  )
}

export default ReportDashboard
