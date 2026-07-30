/**
 * Attack Detail Drawer — slide-in panel for finding and chain details.
 *
 * Adapted from ai-surface's `drawerHTML()` / `openDrawer()` (~120 lines).
 * Shows per-finding evidence, severity, prerequisites, impacts,
 * chain membership, and exploit scripts.
 */

import type { AttackPathData, GraphNodeData } from "../planner/types"
import { SEV_COLORS, esc } from "./svg-builders"

export class AttackDetailDrawer {
  private overlay: HTMLElement
  private panel: HTMLElement
  private content: HTMLElement
  private _open = false

  constructor(container: HTMLElement) {
    // Overlay backdrop
    this.overlay = document.createElement("div")
    this.overlay.className = "ag-drawer-overlay"
    this.overlay.addEventListener("click", () => this.close())

    // Drawer panel
    this.panel = document.createElement("aside")
    this.panel.className = "ag-drawer-panel"
    this.panel.setAttribute("role", "dialog")
    this.panel.setAttribute("aria-modal", "true")

    // Content container
    this.content = document.createElement("div")
    this.content.className = "ag-drawer-content"

    this.panel.appendChild(this.content)
    container.appendChild(this.overlay)
    container.appendChild(this.panel)

    // Keyboard: Escape to close
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this._open) this.close()
    })
  }

  /** Open the drawer with a finding's detail view. */
  openFinding(finding: GraphNodeData, chainData?: AttackPathData): void {
    const sev = finding.data.severity || "INFO"
    const sevColor = SEV_COLORS[sev] ?? "var(--ag-sev-info)"
    const confPct = ((finding.confidence ?? 0.5) * 100).toFixed(0)

    this.content.innerHTML = `
      <div class="ag-drawer-header">
        <span class="ag-severity-badge" style="background:${sevColor}">
          ${esc(sev)}
        </span>
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
          <div class="ag-conf-bar">
            <div class="ag-conf-fill" style="width:${confPct}%"></div>
          </div>
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
          </section>
        ` : ""}

        ${finding.downstream_impacts.length > 0 ? `
          <section class="ag-detail-section">
            <h3>Downstream Impacts</h3>
            <ul class="ag-list">${finding.downstream_impacts.map(i => `<li>${esc(i)}</li>`).join("")}</ul>
          </section>
        ` : ""}

        ${chainData ? this.renderChainSection(chainData, finding) : ""}
      </div>`

    this.open()
  }

  /** Open the drawer with a full chain detail view. */
  openChain(chain: AttackPathData): void {
    const vulnNodes = chain.nodes.filter(n => n.type === "vulnerability")
    const maxSev = vulnNodes.reduce<string>((max, n) => {
      const rank = (s: string) => ({ CRITICAL: 5, HIGH: 4, MEDIUM: 3, LOW: 2, INFO: 1 })[s] ?? 0
      return rank(n.data.severity ?? "") > rank(max) ? (n.data.severity ?? max) : max
    }, "INFO")

    this.content.innerHTML = `
      <div class="ag-drawer-header">
        <span class="ag-severity-badge" style="background:${SEV_COLORS[maxSev] ?? "var(--ag-sev-info)"}">
          ${esc(maxSev)}
        </span>
        <h2>${esc(chain.chain_name ?? `Chain: ${chain.chain_id ?? "unknown"}`)}</h2>
        <span class="ag-risk-score">Risk ${chain.risk_score.toFixed(1)}</span>
        <button class="ag-drawer-close" data-action="close" aria-label="Close">✕</button>
      </div>
      <div class="ag-drawer-body">
        <section class="ag-detail-section">
          <h3>Attack Path (${vulnNodes.length} vulnerability node${vulnNodes.length !== 1 ? "s" : ""})</h3>
          <div class="ag-chain-flow">
            ${vulnNodes.map((n, i) => `
              <div class="ag-chain-step" data-node-id="${esc(n.id)}">
                <span class="ag-step-num">${i + 1}</span>
                <div class="ag-step-body">
                  <span class="ag-step-type">${esc(n.data.type ?? "Unknown")}</span>
                  <span class="ag-step-sev" style="color:${SEV_COLORS[n.data.severity ?? ""] ?? "var(--ag-sev-info)"}">
                    ${esc(n.data.severity ?? "INFO")}
                  </span>
                  <code class="ag-step-endpoint">${esc(n.data.endpoint ?? "")}</code>
                </div>
              </div>
            `).join("")}
          </div>
        </section>

        <section class="ag-detail-section">
          <h3>Risk Score</h3>
          <div class="ag-risk-bar">
            <div class="ag-risk-fill" style="width:${(chain.risk_score / 10) * 100}%; background:${this.riskColor(chain.risk_score)}"></div>
          </div>
          <span class="ag-risk-value">${chain.risk_score.toFixed(1)} / 10.0</span>
        </section>

        ${chain.edges.length > 0 ? `
          <section class="ag-detail-section">
            <h3>Relationships</h3>
            <ul class="ag-list">${chain.edges.map(e => `
              <li><strong>${esc(e.relationship_type)}</strong>: ${esc(e.from_node)} → ${esc(e.to_node)} (×${e.correlation_factor.toFixed(2)})</li>
            `).join("")}</ul>
          </section>
        ` : ""}

        ${this.renderExploitScriptSection(chain)}

        ${this.renderVerificationSection(chain)}
      </div>`

    this.open()
  }

  /** Render exploit script section inside a chain view. */
  private renderExploitScriptSection(chain: AttackPathData): string {
    const script = chain.chain_exploit_script
    if (!script) return ""

    const scriptText = typeof script === "string" ? script : (script.script ?? script.exploit_script ?? JSON.stringify(script, null, 2))
    const steps = script.steps ?? []

    return `
      <section class="ag-detail-section">
        <h3>Exploit Script</h3>
        <details class="ag-script-details">
          <summary class="ag-script-summary">
            Show exploit script (${scriptText.length} chars)
          </summary>
          <pre class="ag-script-pre"><code class="ag-script-code">${esc(scriptText)}</code></pre>
        </details>
        ${steps.length > 0 ? `
          <h4 style="margin-top:8px;font-size:12px;color:var(--ag-edge-base);text-transform:uppercase;letter-spacing:0.5px">Steps</h4>
          <ol class="ag-list ag-step-list">${steps.map((s: any) => `<li>${esc(s.summary ?? s.step ?? "")}</li>`).join("")}</ol>
        ` : ""}
        ${script.impact_summary ? `
          <h4 style="margin-top:8px;font-size:12px;color:var(--ag-edge-base);text-transform:uppercase;letter-spacing:0.5px">Impact</h4>
          <p class="ag-impact-text">${esc(script.impact_summary)}</p>
        ` : ""}
      </section>`
  }

  /** Render verification status section. */
  private renderVerificationSection(chain: AttackPathData): string {
    const verification = chain.verification
    if (!verification) return ""

    const verified = verification.verified ?? verification.passed
    const confidence = verification.confidence ?? ""
    const reason = verification.reason ?? ""

    return `
      <section class="ag-detail-section">
        <h3>Verification Status</h3>
        <div class="ag-verification-status ${verified ? "verified" : "unverified"}">
          <span class="ag-verification-icon">${verified ? "✓" : "○"}</span>
          <span class="ag-verification-label">${verified ? "Verified" : "Not Verified"}</span>
          ${confidence ? `<span class="ag-verification-conf">(${esc(confidence)} confidence)</span>` : ""}
        </div>
        ${reason ? `<p class="ag-verification-reason">${esc(reason)}</p>` : ""}
      </section>`
  }

  /** Render a chain membership section inside a finding drawer. */
  private renderChainSection(chain: AttackPathData, finding: GraphNodeData): string {
    const vulnNodes = chain.nodes.filter(n => n.type === "vulnerability")
    const findingPos = vulnNodes.findIndex(n => n.id === finding.id)

    return `
      <section class="ag-detail-section ag-chain-section">
        <h3>Attack Chain</h3>
        <div class="ag-chain-badge" data-chain-id="${esc(chain.chain_id ?? "")}">
          ${esc(chain.chain_name ?? "Unnamed Chain")}
        </div>
        <div class="ag-chain-position">
          Position ${findingPos + 1} of ${vulnNodes.length} in chain
        </div>
        <div class="ag-chain-risk">
          <strong>Risk score:</strong> ${chain.risk_score.toFixed(1)}
        </div>
        <div class="ag-chain-path-mini">
          ${vulnNodes.map((n, i) => {
            const isCurrent = n.id === finding.id
            return `
              <span class="ag-chain-mini-step${isCurrent ? " current" : ""}"
                    style="background:${SEV_COLORS[n.data.severity ?? ""] ?? "var(--ag-sev-info)"}">
                ${esc(n.data.type ?? "?")}
              </span>
              ${i < vulnNodes.length - 1 ? '<span class="ag-chain-arrow">→</span>' : ""}
            `
          }).join("")}
        </div>
        <button class="ag-btn ag-btn-small" data-action="view-chain" data-chain-id="${esc(chain.chain_id ?? "")}">
          View Full Chain
        </button>
      </section>`
  }

  /** Risk score color (green → yellow → red). */
  private riskColor(score: number): string {
    if (score >= 8) return "#dc2626"
    if (score >= 5) return "#ea580c"
    if (score >= 3) return "#ca8a04"
    return "#2563eb"
  }

  // ── Open / Close ──

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
