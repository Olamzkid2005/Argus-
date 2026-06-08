/**
 * EvidenceViewer — Displays evidence artifacts for a finding.
 *
 * Text artifacts are shown inline with content loaded on expand.
 * Binary artifacts show metadata with "Open externally" action.
 * Supports pagination for large numbers of artifacts.
 */
import { createSignal, createMemo, onMount, Show, For } from "solid-js"
import { useTheme } from "@tui/context/theme"

interface EvidenceViewerProps {
  findingId: string
}

interface ArtifactItem {
  id: string
  packageId: string
  path: string
  type: string
  sizeBytes: number
  content?: string
  loading?: boolean
}

const TEXT_TYPES = new Set(["json", "xml", "txt", "html", "css", "js", "ts", "py", "java", "go", "rs", "rb", "php", "http", "response", "request", "log", "har", "csv", "yaml", "yml", "md"])
const BINARY_TYPES = new Set(["png", "jpg", "jpeg", "gif", "pdf", "zip", "binary", "exe", "bin", "ico", "svg"])

export function EvidenceViewer(props: EvidenceViewerProps) {
  const { theme } = useTheme()
  const [artifacts, setArtifacts] = createSignal<ArtifactItem[]>([])
  const [expanded, setExpanded] = createSignal<Set<string>>(new Set())
  const [contents, setContents] = createSignal<Record<string, string>>({})
  const [loading, setLoading] = createSignal(true)
  const [page, setPage] = createSignal(1)
  const pageSize = 10

  onMount(async () => {
    try {
      const { EngagementStore } = await import("@/argus/engagement/store")
      const store = new EngagementStore()
      const packages = store.getEvidencePackages(props.findingId)
      const allArtifacts: ArtifactItem[] = []
      for (const pkg of packages) {
        const arts = store.getArtifacts(pkg.id)
        for (const a of arts) {
          allArtifacts.push({
            id: a.id,
            packageId: pkg.id,
            path: a.path,
            type: a.type,
            sizeBytes: a.sizeBytes,
          })
        }
      }
      setArtifacts(allArtifacts)
      setLoading(false)
    } catch {
      setLoading(false)
    }
  })

  const isTextType = (type: string): boolean => {
    const t = type.toLowerCase()
    if (BINARY_TYPES.has(t)) return false
    if (TEXT_TYPES.has(t)) return true
    // Check path extension as fallback for unknown types
    return false // Default: treat unknown types as binary (safer)
  }

  const isBinaryType = (type: string): boolean => {
    const t = type.toLowerCase()
    if (BINARY_TYPES.has(t)) return true
    // Check path extension as fallback for unknown types
    return true // Default: treat unknown types as binary (safer)
  }

  const totalPages = createMemo(() => Math.max(1, Math.ceil(artifacts().length / pageSize)))
  const pagedArtifacts = createMemo(() => {
    const items = artifacts()
    return items.slice((page() - 1) * pageSize, page() * pageSize)
  })

  const toggleExpand = async (artifact: ArtifactItem) => {
    const s = new Set(expanded())
    if (s.has(artifact.id)) {
      s.delete(artifact.id)
      setExpanded(s)
      return
    }

    s.add(artifact.id)
    setExpanded(s)

    // Lazy-load content for text artifacts on first expand
    if (!isTextType(artifact.type)) return
    if (contents()[artifact.id] !== undefined) return
    if (artifact.loading) return

    setArtifacts((prev) => prev.map((a) => a.id === artifact.id ? { ...a, loading: true } : a))
    try {
      const { realpathSync, readFileSync, existsSync } = await import("fs")
      const { homedir } = await import("os")
      const { join, resolve } = await import("path")
      const rawBaseDir = join(homedir(), ".argus", "artifacts")
      const baseDir = existsSync(rawBaseDir) ? realpathSync(rawBaseDir) : rawBaseDir
      const joinedPath = resolve(baseDir, artifact.path)
      const resolvedPath = existsSync(joinedPath) ? realpathSync(joinedPath) : joinedPath
      if (!resolvedPath.startsWith(baseDir + "/")) {
        setContents((prev) => ({ ...prev, [artifact.id]: "[Security: Invalid artifact path]" }))
      } else if (existsSync(resolvedPath)) {
        const content = readFileSync(resolvedPath, "utf-8")
        setContents((prev) => ({ ...prev, [artifact.id]: content }))
      } else {
        setContents((prev) => ({ ...prev, [artifact.id]: "[File not found on disk]" }))
      }
    } catch {
      setContents((prev) => ({ ...prev, [artifact.id]: "[Could not load artifact content]" }))
    }
    setArtifacts((prev) => prev.map((a) => a.id === artifact.id ? { ...a, loading: false } : a))
  }

  const artifactTypeIcon = (type: string): string => {
    const t = type.toLowerCase()
    if (["png", "jpg", "jpeg", "gif"].includes(t)) return "🖼"
    if (t === "har" || t === "http" || t === "request" || t === "response") return "↔"
    if (t === "log") return "📋"
    if (t === "json" || t === "xml") return "📄"
    if (t === "html") return "🌐"
    return "📎"
  }

  return (
    <box flexDirection="column" paddingX={1}>
      <Show when={!loading()} fallback={<text fg={theme.primary}>Loading evidence...</text>}>
        <Show when={artifacts().length > 0} fallback={
          <text fg={theme.textMuted}>No evidence available for this finding.</text>
        }>
          <For each={pagedArtifacts()}>
            {(artifact) => (
              <box flexDirection="column" paddingTop={1}>
                <box flexDirection="row" gap={1} onClick={() => toggleExpand(artifact)}>
                  <text fg={theme.primary}>{expanded().has(artifact.id) ? "▼" : "▶"}</text>
                  <text>{artifactTypeIcon(artifact.type)}</text>
                  <text fg={theme.textMuted}>{artifact.type}</text>
                  <text fg={theme.textMuted}>{artifact.path.split("/").pop()}</text>
                  <Show when={artifact.sizeBytes}>
                    <text fg={theme.textMuted}>({(artifact.sizeBytes / 1024).toFixed(1)} KB)</text>
                  </Show>
                </box>
                <Show when={expanded().has(artifact.id)}>
                  <box paddingLeft={5} paddingTop={1}>
                    <Show when={isBinaryType(artifact.type)} fallback={
                      <Show when={!artifact.loading} fallback={
                        <text fg={theme.primary}>⠋ Loading content...</text>
                      }>
                        <Show when={contents()[artifact.id] !== undefined} fallback={
                          <text fg={theme.textMuted}>Click to load content</text>
                        }>
                          <box flexDirection="column">
                            <Show when={contents()[artifact.id].length > 2000}>
                              <text fg={theme.textMuted}>[First 2000 of {contents()[artifact.id].length} chars]</text>
                            </Show>
                            <text fg={theme.text} wrap="wrap">{contents()[artifact.id].slice(0, 2000)}</text>
                          </box>
                        </Show>
                      </Show>
                    }>
                      <text fg={theme.textMuted}>Binary artifact — open externally</text>
                    </Show>
                  </box>
                </Show>
              </box>
            )}
          </For>

          {/* Pagination */}
          <Show when={totalPages() > 1}>
            <box flexDirection="row" gap={1} paddingTop={1}>
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
export default EvidenceViewer
