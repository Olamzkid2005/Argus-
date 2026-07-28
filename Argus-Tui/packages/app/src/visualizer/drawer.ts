/**
 * Attack Detail Drawer — slide-in panel for finding and chain details.
 * Adapted from the opencode package's visualizer.
 */

import { SEV_COLORS, esc } from "./svg-builders"
import type { AttackPathData, GraphNodeData } from "./index"

export class AttackDetailDrawer {
  private overlay: HTMLElement
  private panel: HTMLElement
  private content: HTMLElement
  private _open = false

  constructor(container: HTMLElement) {
    this.overlay = document.createElement("div")
    this.overlay.className = "ag-drawer-overlay"
    this.overlay.addEventListener("click", () => this.close())

    this.panel = document.createElement("aside")
    this.panel.className = "ag-drawer-panel"
    this.panel.setAttribute("role", "dialog")
    this.panel.setAttribute("aria-modal", "true")

    this.content = document.createElement("div")
    this.content.className = "ag-drawer-content"

    this.panel.appendChild(this.content)
    container.appendChild(this.overlay)
    container.appendChild(this.panel)

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this._open) this.close()
    })
  }

  openFinding(finding: GraphNodeData, chainData?: AttackPathData): void {
    const sev = finding.data.severity || "INFO"
    const sevColor = SEV_COLORS[sev] ?? "var(--ag-sev-info)"
    const confPct = ((finding.confidence ?? 0.5) * 100).toFixed(0)

    this.content.innerHTML = `
      <div class="ag-drawer-header">
        <span class="ag-severity-badge" style="background:${sevColor}">${esc(sev)}</span>
        <h2>${esc(finding.data.type ?? "Unknown")}</h2>
        <button class="ag-drawer-close" data-action="close" aria-label="Close">✕</button>
      </div>
      <div class="ag-drawer-body">
        <section class="ag-detail-section">
          <h3>Endpoint</h3>
          <code class="ag-endpoint">${esc(finding.data.endpoint ?? finding.data.url ?? "—")}</code>
        </section>
        <section class="ag-detail-section">
          <h3>Confidence</h3>
          <div class="ag-conf-bar"><div class="ag-conf-fill" style="width:${confPct}%"></div></div>
          <span class="ag-conf-pct">${confPct}%</span>
        </section>
        <section class="ag-detail-section">
          <h3>CVSS</h3>
          <span class="ag-cvss">${finding.cvss != null ? finding.cvss.toFixed(1) : "—"}</span>
        </section>
        ${finding.prerequisites.length > 0 ? `
          <section class="ag-detail-section">
            <h3>Prerequisites</h3>
            <ul class="ag-list">${finding.prerequisites.map(p => `<li>${esc(p)}</li>`).join("")}</ul>
          </section>` : ""}
        ${finding.downstream_impacts.length > 0 ? `
          <section class="ag-detail-section">
            <h3>Downstream Impacts</h3>
            <ul class="ag-list">${finding.downstream_impacts.map(i => `<li>${esc(i)}</li>`).join("")}</ul>
          </section>` : ""}
        ${chainData ? this.renderChainSection(chainData, finding) : ""}
      </div>`
    this.open()
  }

  openChain(chain: AttackPathData): void {
    const vulnNodes = chain.nodes.filter(n => n.type === "vulnerability")
    const maxSev = vulnNodes.reduce<string>((max, n) => {
      const rank = (s: string) => ({ CRITICAL: 5, HIGH: 4, MEDIUM: 3, LOW: 2, INFO: 1 })[s] ?? 0
      return rank(n.data.severity ?? "") > rank(max) ? (n.data.severity ?? max) : max
    }, "INFO")

    this.content.innerHTML = `
      <div class="ag-drawer-header">
        <span class="ag-severity-badge" style="background:${SEV_COLORS[maxSev] ?? "var(--ag-sev-info)"}">${esc(maxSev)}</span>
        <h2>${esc(chain.chain_name ?? `Chain: ${chain.chain_id ?? "unknown"}`)}</h2>
        <span class="ag-risk-score">Risk ${chain.risk_score.toFixed(1)}</span>
        <button class="ag-drawer-close" data-action="close" aria-label="Close">✕</button>
      </div>
      <div class="ag-drawer-body">
        <section class="ag-detail-section">
          <h3>Attack Path (${vulnNodes.length} vulnerability node${vulnNodes.length !== 1 ? "s" : ""})</h3>
          <div class="ag-chain-flow">
            ${vulnNodes.map((n, i) => `
              <div class="ag-chain-step">
                <span class="ag-step-num">${i + 1}</span>
                <div class="ag-step-body">
                  <span class="ag-step-type">${esc(n.data.type ?? "Unknown")}</span>
                  <span class="ag-step-sev" style="color:${SEV_COLORS[n.data.severity ?? ""] ?? "var(--ag-sev-info)"}">${esc(n.data.severity ?? "INFO")}</span>
                  <code class="ag-step-endpoint">${esc(n.data.endpoint ?? "")}</code>
                </div>
              </div>`).join("")}
          </div>
        </section>
        <section class="ag-detail-section">
          <h3>Risk Score</h3>
          <div class="ag-risk-bar"><div class="ag-risk-fill" style="width:${(chain.risk_score / 10) * 100}%;background:${this.riskColor(chain.risk_score)}"></div></div>
          <span class="ag-risk-value">${chain.risk_score.toFixed(1)} / 10.0</span>
        </section>
        ${chain.edges.length > 0 ? `
          <section class="ag-detail-section">
            <h3>Relationships</h3>
            <ul class="ag-list">${chain.edges.map(e => `<li><strong>${esc(e.relationship_type)}</strong>: ${esc(e.from_node)} → ${esc(e.to_node)} (×${e.correlation_factor.toFixed(2)})</li>`).join("")}</ul>
          </section>` : ""}
      </div>`
    this.open()
  }

  private renderChainSection(chain: AttackPathData, finding: GraphNodeData): string {
    const vulnNodes = chain.nodes.filter(n => n.type === "vulnerability")
    const findingPos = vulnNodes.findIndex(n => n.id === finding.id)
    return `
      <section class="ag-detail-section ag-chain-section">
        <h3>Attack Chain</h3>
        <div class="ag-chain-badge" data-chain-id="${esc(chain.chain_id ?? "")}">${esc(chain.chain_name ?? "Unnamed Chain")}</div>
        <div class="ag-chain-position">Position ${findingPos + 1} of ${vulnNodes.length} in chain</div>
        <div class="ag-chain-risk"><strong>Risk score:</strong> ${chain.risk_score.toFixed(1)}</div>
        <div class="ag-chain-path-mini">
          ${vulnNodes.map((n, i) => {
            const isCurrent = n.id === finding.id
            return `<span class="ag-chain-mini-step${isCurrent ? " current" : ""}" style="background:${SEV_COLORS[n.data.severity ?? ""] ?? "var(--ag-sev-info)"}">${esc(n.data.type ?? "?")}</span>${i < vulnNodes.length - 1 ? '<span class="ag-chain-arrow">→</span>' : ""}`
          }).join("")}
        </div>
      </section>`
  }

  private riskColor(score: number): string {
    if (score >= 8) return "#dc2626"
    if (score >= 5) return "#ea580c"
    if (score >= 3) return "#ca8a04"
    return "#2563eb"
  }

  open(): void {
    this._open = true
    this.overlay.classList.add("open")
    this.panel.classList.add("open")
    document.body.style.overflow = "hidden"
  }

  close(): void {
    this._open = false
    this.overlay.classList.remove("open")
    this.panel.classList.remove("open")
    document.body.style.overflow = ""
  }

  get isOpen(): boolean {
    return this._open
  }
}
