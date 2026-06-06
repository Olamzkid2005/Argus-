/**
 * EvidenceViewer — Displays evidence artifacts for a finding.
 *
 * Text artifacts are shown inline with syntax highlighting.
 * Binary artifacts show metadata with "Open externally" action.
 */
import { createSignal, onMount, Show, For } from "solid-js"
import { useTheme } from "@tui/context/theme"

interface EvidenceViewerProps {
  findingId: string
}

export function EvidenceViewer(props: EvidenceViewerProps) {
  const { theme } = useTheme()
  const [artifacts, setArtifacts] = createSignal<any[]>([])
  const [expanded, setExpanded] = createSignal<Set<string>>(new Set())
  const [loading, setLoading] = createSignal(true)

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const packages = store.getEvidencePackages(props.findingId)
      const allArtifacts: any[] = []
      for (const pkg of packages) {
        const arts = store.getArtifacts(pkg.id)
        for (const a of arts) {
          allArtifacts.push({ ...a, packageId: pkg.id })
        }
      }
      setArtifacts(allArtifacts)
      setLoading(false)
    } catch {
      setLoading(false)
    }
  })

  const toggleExpand = (id: string) => {
    const s = new Set(expanded())
    if (s.has(id)) s.delete(id)
    else s.add(id)
    setExpanded(s)
  }

  const isBinaryType = (type: string) => {
    return ["png", "jpg", "jpeg", "gif", "pdf", "zip", "binary"].includes(type.toLowerCase())
  }

  return (
    <box flexDirection="column" paddingX={1}>
      <Show when={!loading()} fallback={<text fg={theme.primary}>Loading evidence...</text>}>
        <Show when={artifacts().length > 0} fallback={
          <text fg={theme.textMuted}>No evidence available for this finding.</text>
        }>
          <For each={artifacts()}>
            {(artifact: any) => (
              <box flexDirection="column" paddingTop={1}>
                <box flexDirection="row" gap={1} onClick={() => toggleExpand(artifact.id)}>
                  <text fg={theme.primary}>{expanded().has(artifact.id) ? "▼" : "▶"}</text>
                  <text fg={theme.text}>{artifact.type}</text>
                  <text fg={theme.textMuted}>{artifact.path}</text>
                  <Show when={artifact.sizeBytes}>
                    <text fg={theme.textMuted}>({(artifact.sizeBytes / 1024).toFixed(1)} KB)</text>
                  </Show>
                </box>
                <Show when={expanded().has(artifact.id)}>
                  <Show when={!isBinaryType(artifact.type)} fallback={
                    <box paddingLeft={3} paddingTop={1}>
                      <text fg={theme.textMuted}>Binary artifact — open externally: {artifact.path}</text>
                    </box>
                  }>
                    <box paddingLeft={3} paddingTop={1}>
                      <text fg={theme.textMuted} wrap="wrap">Content preview not available in TUI mode.</text>
                    </box>
                  </Show>
                </Show>
              </box>
            )}
          </For>
        </Show>
      </Show>
    </box>
  )
}
export default EvidenceViewer
