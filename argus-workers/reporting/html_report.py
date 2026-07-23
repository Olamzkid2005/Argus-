"""
Self-contained HTML Report Renderer.

Pure function: takes structured report data, returns an HTML string.
No file I/O. No subprocess calls. No browser launches. No side effects.

Features:
- Dark theme severity cards with CSS bar chart visualization
- Top CWEs section with horizontal bar charts
- Compliance framework tags (OWASP, PCI DSS, SOC2) per finding
- Expandable finding details with evidence/payload display
- Executive summary section
- Search/filter functionality
- Copy Fix button for remediation
"""

import datetime
from html import escape
from typing import Any

from tool_core._compat import utc

# Severity colors (GitHub-dark inspired)
_SEVERITY_STYLE: dict[str, dict[str, str]] = {
    "CRITICAL": {"bg": "#8b0000", "fg": "#ffffff", "label": "CRITICAL"},
    "HIGH": {"bg": "#d73a4a", "fg": "#ffffff", "label": "HIGH"},
    "MEDIUM": {"bg": "#d29922", "fg": "#ffffff", "label": "MEDIUM"},
    "LOW": {"bg": "#0e8a16", "fg": "#ffffff", "label": "LOW"},
    "INFO": {"bg": "#58a6ff", "fg": "#ffffff", "label": "INFO"},
}

# Compliance framework mappings (finding_type -> framework ref)
_OWASP_MAP: dict[str, str] = {
    "SQL_INJECTION": "A03:2021 Injection",
    "COMMAND_INJECTION": "A03:2021 Injection",
    "XSS": "A03:2021 Injection",
    "XXE": "A03:2021 Injection",
    "BROKEN_ACCESS_CONTROL": "A01:2021 Broken Access Control",
    "IDOR": "A01:2021 Broken Access Control",
    "PATH_TRAVERSAL": "A01:2021 Broken Access Control",
    "CRYPTOGRAPHIC_FAILURE": "A02:2021 Cryptographic Failures",
    "WEAK_TLS": "A02:2021 Cryptographic Failures",
    "INSECURE_DESIGN": "A04:2021 Insecure Design",
    "SECURITY_MISCONFIGURATION": "A05:2021 Security Misconfiguration",
    "VULNERABLE_COMPONENT": "A06:2021 Vulnerable Components",
    "AUTH_FAILURE": "A07:2021 Auth Failures",
    "SESSION_MANAGEMENT": "A07:2021 Auth Failures",
    "SSRF": "A10:2021 SSRF",
    "LOGGING_FAILURE": "A09:2021 Logging Failures",
}

_PCI_MAP: dict[str, str] = {
    "SQL_INJECTION": "PCI 6.5.1",
    "XSS": "PCI 6.5.7",
    "BROKEN_ACCESS_CONTROL": "PCI 6.5.8",
    "IDOR": "PCI 6.5.8",
    "WEAK_TLS": "PCI 4.1",
    "AUTH_FAILURE": "PCI 8.2",
    "SECURITY_MISCONFIGURATION": "PCI 2.2",
    "VULNERABLE_COMPONENT": "PCI 6.3",
    "LOGGING_FAILURE": "PCI 10.2",
}

_SOC2_MAP: dict[str, str] = {
    "SQL_INJECTION": "SOC2 CC7.1",
    "XSS": "SOC2 CC7.1",
    "BROKEN_ACCESS_CONTROL": "SOC2 CC6.1",
    "IDOR": "SOC2 CC6.1",
    "WEAK_TLS": "SOC2 CC6.7",
    "AUTH_FAILURE": "SOC2 CC6.1",
    "SECURITY_MISCONFIGURATION": "SOC2 CC7.1",
    "VULNERABLE_COMPONENT": "SOC2 CC7.1",
    "LOGGING_FAILURE": "SOC2 CC7.2",
}


def _escape(val: Any) -> str:
    """HTML-escape a value, returning empty string for None."""
    if val is None:
        return ""
    return escape(str(val))


def _severity_badge_css(severity: str) -> str:
    style = _SEVERITY_STYLE.get(severity.upper(), _SEVERITY_STYLE["INFO"])
    return f"background:{style['bg']};color:{style['fg']}"


def _get_compliance_tags(finding_type: str) -> list[dict[str, str]]:
    """Get compliance framework tags for a finding type."""
    ftype = finding_type.upper()
    tags: list[dict[str, str]] = []
    owasp = _OWASP_MAP.get(ftype)
    pci = _PCI_MAP.get(ftype)
    soc2 = _SOC2_MAP.get(ftype)
    if owasp:
        tags.append({"label": owasp, "framework": "OWASP"})
    if pci:
        tags.append({"label": pci, "framework": "PCI"})
    if soc2:
        tags.append({"label": soc2, "framework": "SOC2"})
    return tags


def _severity_cards(severity_breakdown: dict | None) -> str:
    """Generate severity summary card HTML with bar chart."""
    max_count = max((severity_breakdown or {}).values()) if severity_breakdown else 1
    max_count = max(max_count, 1)

    cards_html = ""
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
        count = (severity_breakdown or {}).get(sev, 0)
        style = _SEVERITY_STYLE.get(sev, _SEVERITY_STYLE["INFO"])
        pct = (count / max_count) * 100 if max_count > 0 else 0
        bar_color = style["bg"]
        cards_html += f"""
      <div class="card {sev.lower()}">
        <div class="count">{count}</div>
        <div class="label" style="color:{style['bg']}">{sev}</div>
        <div class="bar-track">
          <div class="bar-fill" style="width:{pct:.0f}%;background:{bar_color}"></div>
        </div>
      </div>"""
    return cards_html


def _cwe_section(severity_breakdown: dict | None, findings: list[dict]) -> str:
    """Generate Top CWEs section with CSS bar chart."""
    from collections import Counter

    cwe_counts: Counter[str] = Counter()
    for f in findings:
        cwe = (f.get("cwe_id") or "").strip()
        if cwe:
            cwe_counts[cwe] += 1

    if not cwe_counts:
        return ""

    max_count = max(cwe_counts.values())
    top5 = cwe_counts.most_common(5)

    rows = ""
    for cwe_id, count in top5:
        pct = (count / max_count) * 100
        rows += f"""
        <div class="cwe-row">
          <span class="cwe-label">{_escape(cwe_id)}</span>
          <div class="bar-track bar-track-sm">
            <div class="bar-fill bar-fill-cwe" style="width:{pct:.0f}%"></div>
          </div>
          <span class="cwe-count">{count}</span>
        </div>"""

    return f"""
    <h2>🔬 Top CWEs</h2>
    <div class="cwe-section">
      {rows}
    </div>"""


def _compliance_overview(severity_breakdown: dict | None, findings: list[dict]) -> str:
    """Generate compliance framework overview section."""
    from collections import Counter, defaultdict

    framework_findings: dict[str, Counter[str]] = defaultdict(Counter)
    for f in findings:
        ftype = (f.get("finding_type") or f.get("type") or "").upper()
        tags = _get_compliance_tags(ftype)
        for tag in tags:
            framework_findings[tag["framework"]][tag["label"]] += 1

    if not framework_findings:
        return ""

    sections = ""
    for framework in ("OWASP", "PCI", "SOC2"):
        refs = framework_findings.get(framework)
        if not refs:
            continue
        max_count = max(refs.values())
        items = ""
        for ref, count in refs.most_common(5):
            pct = (count / max_count) * 100 if max_count else 0
            severity = "critical" if count >= 2 else "high" if count >= 1 else "low"
            items += f"""
            <div class="compliance-item {severity}">
              <span class="compliance-ref">{_escape(ref)}</span>
              <div class="bar-track bar-track-sm">
                <div class="bar-fill bar-fill-{severity}" style="width:{pct:.0f}%"></div>
              </div>
              <span class="compliance-count">{count}</span>
            </div>"""
        sections += f"""
        <div class="compliance-column">
          <h3 class="compliance-fw-label">{framework}</h3>
          {items}
        </div>"""

    if not sections:
        return ""

    return f"""
    <h2>📋 Compliance Overview</h2>
    <div class="compliance-section">
      {sections}
    </div>"""


def _findings_rows(findings: list[dict]) -> str:
    """Generate findings table rows with expandable details, evidence, and compliance tags."""
    rows = ""
    for i, f in enumerate(findings):
        sev = (f.get("severity") or "INFO").upper()
        finding_type = _escape(f.get("finding_type") or f.get("type") or "Unknown")
        endpoint = _escape(f.get("endpoint") or "N/A")
        title = _escape(f.get("title") or finding_type)
        description = _escape(f.get("description") or "")
        remediation = _escape(f.get("remediation") or "")
        cwe = _escape(f.get("cwe_id") or "")
        evidence = f.get("evidence") or {}
        detail_id = f"detail-{i}"

        # Compliance tags
        compliance_tags = _get_compliance_tags(f.get("finding_type") or f.get("type") or "")
        tags_html = ""
        tag_colors = {"OWASP": "#1f6feb", "PCI": "#3fb950", "SOC2": "#d29922"}
        for tag in compliance_tags:
            color = tag_colors.get(tag["framework"], "#8b949e")
            tags_html += f"""<span class="compliance-tag" style="border-color:{color};color:{color}">{_escape(tag["label"])}</span>\n"""

        # Finding detail panel
        detail_html = ""
        has_detail = any([description, remediation, cwe, evidence])
        if has_detail:
            parts: list[str] = [
                f'<tr id="{detail_id}-row" class="finding-detail-row">',
                '<td colspan="5">',
                '<div class="finding-detail open">',
            ]
            if description:
                parts.append(f'<h4>📝 Description</h4><p>{description}</p>')
            if cwe:
                parts.append(f'<h4>🔗 CWE Reference</h4><p>{cwe}</p>')
            if evidence:
                ev_html = ""
                if isinstance(evidence, dict):
                    for key, val in evidence.items():
                        val_str = _escape(str(val)[:500])
                        ev_html += f'<div class="evidence-field"><strong>{_escape(key)}:</strong> <code>{val_str}</code></div>'
                elif isinstance(evidence, str):
                    ev_html = f'<pre>{_escape(evidence[:1000])}</pre>'
                if ev_html:
                    parts.append(f"<h4>🔍 Evidence</h4>{ev_html}")
            if remediation:
                import json
                safe_remediation = json.dumps(remediation)
                parts.append(f'<h4>🛠️ Remediation</h4><p>{remediation}</p>')
                parts.append(
                    f'<button class="copy-btn" onclick="copyFix({safe_remediation}, this)">'
                    f'📋 Copy Fix</button>'
                )
            parts.extend(["</div>", "</td>", "</tr>"])
            detail_html = "".join(parts)

        rows += f"""
        <tr>
          <td><span class="severity-badge" style="{_severity_badge_css(sev)}">{sev}</span></td>
          <td>{finding_type}{tags_html}</td>
          <td>{endpoint}</td>
          <td>{title}</td>
          <td><a class="finding-toggle" onclick="toggleDetail('{detail_id}')">Details</a></td>
        </tr>"""
        rows += detail_html

    return rows


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root {{
    --bg: #0d1117;
    --bg-card: #161b22;
    --bg-hover: #1c2128;
    --border: #30363d;
    --text: #e6edf3;
    --text-muted: #8b949e;
    --accent: #58a6ff;
    --success: #3fb950;
    --warning: #d29922;
    --danger: #f85149;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 32px 24px;
    max-width: 1200px;
    margin: 0 auto;
  }}
  h1 {{ font-size: 28px; font-weight: 600; margin-bottom: 8px; }}
  h2 {{ font-size: 20px; font-weight: 600; margin: 32px 0 16px;
        border-bottom: 1px solid var(--border); padding-bottom: 8px; }}
  .meta {{ color: var(--text-muted); font-size: 14px; margin-bottom: 24px; }}
  .meta span {{ margin-right: 20px; }}

  /* ── Severity Cards ───────────────────────────────────────── */

  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    text-align: center;
  }}
  .card .count {{ font-size: 36px; font-weight: 700; line-height: 1.2; }}
  .card .label {{ font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; }}
  .card.critical {{ border-top: 3px solid #8b0000; }} .card.critical .count {{ color: var(--danger); }}
  .card.high {{ border-top: 3px solid #d73a4a; }} .card.high .count {{ color: #d73a4a; }}
  .card.medium {{ border-top: 3px solid #d29922; }} .card.medium .count {{ color: var(--warning); }}
  .card.low {{ border-top: 3px solid #0e8a16; }} .card.low .count {{ color: var(--success); }}
  .card.info {{ border-top: 3px solid #58a6ff; }} .card.info .count {{ color: var(--accent); }}

  /* Bar chart (CSS only) */
  .bar-track {{
    height: 6px;
    background: #21262d;
    border-radius: 3px;
    margin-top: 8px;
    overflow: hidden;
  }}
  .bar-track-sm {{ height: 4px; margin-top: 4px; }}
  .bar-fill {{ height: 100%; border-radius: 3px; transition: width 0.6s ease; }}

  /* ── CWE Section ──────────────────────────────────────────── */

  .cwe-section {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 24px;
  }}
  .cwe-row {{
    display: flex; align-items: center; gap: 12px;
    padding: 6px 0;
  }}
  .cwe-label {{ font-size: 13px; min-width: 90px; font-weight: 600; font-family: monospace; }}
  .cwe-row .bar-track {{ flex: 1; }}
  .bar-fill-cwe {{ background: var(--accent); }}
  .cwe-count {{ font-size: 13px; min-width: 30px; text-align: right; color: var(--text-muted); }}

  /* ── Compliance Overview ──────────────────────────────────── */

  .compliance-section {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
  }}
  .compliance-column {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
  }}
  .compliance-fw-label {{
    font-size: 14px; font-weight: 600; margin-bottom: 12px;
    padding-bottom: 8px; border-bottom: 1px solid var(--border);
  }}
  .compliance-item {{
    display: flex; align-items: center; gap: 8px;
    padding: 4px 0; font-size: 12px;
  }}
  .compliance-item .bar-track {{ flex: 1; }}
  .compliance-ref {{ min-width: 100px; font-family: monospace; }}
  .compliance-count {{ min-width: 20px; text-align: right; color: var(--text-muted); }}
  .bar-fill-critical {{ background: var(--danger); }}
  .bar-fill-high {{ background: var(--warning); }}
  .bar-fill-low {{ background: var(--success); }}
  .compliance-item.critical .compliance-ref {{ color: var(--danger); }}
  .compliance-item.high .compliance-ref {{ color: var(--warning); }}

  /* Compliance tags on findings */
  .compliance-tag {{
    display: inline-block;
    font-size: 10px;
    border: 1px solid;
    border-radius: 4px;
    padding: 0 4px;
    margin: 0 2px;
    white-space: nowrap;
    font-family: monospace;
  }}

  /* ── Search ───────────────────────────────────────────────── */

  .search-bar {{
    width: 100%;
    padding: 10px 14px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    font-size: 14px;
    margin-bottom: 16px;
    outline: none;
  }}
  .search-bar:focus {{ border-color: var(--accent); }}

  /* ── Findings Table ───────────────────────────────────────── */

  table {{ width: 100%; border-collapse: collapse; }}
  th {{
    text-align: left;
    padding: 10px 12px;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    border-bottom: 2px solid var(--border);
  }}
  td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); font-size: 14px; vertical-align: top; }}
  tr:hover td {{ background: var(--bg-hover); }}

  .severity-badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    color: #ffffff;
  }}

  /* Finding type cell with compliance tags */
  td:nth-child(2) {{ white-space: normal; word-break: break-word; }}

  /* ── Finding Details ──────────────────────────────────────── */

  .finding-detail {{
    display: none;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    margin: 8px 0;
  }}
  .finding-detail.open {{ display: block; }}
  .finding-detail h4 {{ font-size: 14px; margin-bottom: 8px; margin-top: 12px; color: var(--accent); }}
  .finding-detail h4:first-child {{ margin-top: 0; }}
  .finding-detail p {{ font-size: 13px; margin-bottom: 8px; color: var(--text-muted); line-height: 1.7; }}
  .finding-detail pre {{
    background: #0d1117;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px;
    font-size: 12px;
    overflow-x: auto;
    margin-bottom: 8px;
    white-space: pre-wrap;
  }}
  .finding-detail code {{
    background: #0d1117;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 12px;
    color: var(--accent);
  }}
  .finding-detail-row td {{ padding: 0; background: transparent !important; }}

  .evidence-field {{
    margin-bottom: 4px;
    font-size: 13px;
    color: var(--text-muted);
  }}
  .evidence-field code {{
    color: #e6edf3;
    background: #161b22;
  }}

  .finding-toggle {{
    cursor: pointer;
    color: var(--accent);
    font-size: 12px;
    text-decoration: none;
  }}
  .finding-toggle:hover {{ text-decoration: underline; }}

  .copy-btn {{
    display: inline-block;
    padding: 4px 12px;
    background: #21262d;
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-size: 12px;
    cursor: pointer;
    transition: background 0.2s;
    margin-top: 8px;
  }}
  .copy-btn:hover {{ background: #30363d; }}
  .copy-btn.copied {{ background: var(--success); border-color: var(--success); }}

  .summary {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 24px;
    font-size: 14px;
    line-height: 1.8;
  }}

  footer {{
    margin-top: 48px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
    font-size: 12px;
    color: var(--text-muted);
    text-align: center;
  }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="meta">
  <span>🎯 Target: <strong>{target}</strong></span>
  <span>📅 Generated: <strong>{scan_date}</strong></span>
  <span>📊 Total findings: <strong>{total_findings}</strong></span>
</div>

{severity_cards}

{executive_summary_html}

{cwe_section}

{compliance_section}

<h2>🔍 Findings</h2>
<input type="text" class="search-bar" id="searchInput" placeholder="Search findings by title, type, endpoint, severity, CWE..." oninput="filterFindings()">

<table id="findingsTable">
<thead>
<tr>
  <th>Severity</th>
  <th>Type / Compliance</th>
  <th>Endpoint</th>
  <th>Title</th>
  <th></th>
</tr>
</thead>
<tbody>
{findings_rows}
</tbody>
</table>

<footer>Report generated by <strong>Argus Security Assessment Platform</strong></footer>

<script>
function filterFindings() {{
  const q = document.getElementById('searchInput').value.toLowerCase();
  const rows = document.querySelectorAll('#findingsTable tbody tr');
  for (const row of rows) {{
    const text = row.textContent.toLowerCase();
    row.style.display = text.includes(q) ? '' : 'none';
  }}
}}

function toggleDetail(id) {{
  const el = document.getElementById(id + '-row');
  if (el) {{
    const detailDiv = el.querySelector('.finding-detail');
    if (detailDiv) {{
      detailDiv.classList.toggle('open');
    }}
  }}
}}

function copyFix(cmd, btn) {{
  navigator.clipboard.writeText(cmd).then(() => {{
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => {{ btn.textContent = 'Copy Fix'; btn.classList.remove('copied'); }}, 2000);
  }});
}}
</script>
</body>
</html>"""


def render_html_report(
    title: str = "Security Assessment Report",
    target: str = "",
    findings: list[dict] | None = None,
    scan_date: str | None = None,
    severity_breakdown: dict | None = None,
    executive_summary: str = "",
) -> str:
    """Generate a self-contained HTML report — single file, zero external deps.

    This is a PURE function:
    - No file I/O
    - No subprocess calls
    - No browser launches
    - No side effects

    Args:
        title: Report title.
        target: Target URL or description.
        findings: List of finding dicts. Each should have: severity, type/finding_type,
                  endpoint, title, description, remediation, cwe_id, evidence.
        scan_date: ISO-formatted date string. Auto-generated if None.
        severity_breakdown: Dict of severity -> count. Computed if None.
        executive_summary: Free-text executive summary.

    Returns:
        Complete HTML string (self-contained, no external resources).
    """
    findings = findings or []
    scan_date = scan_date or datetime.datetime.now(utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    if severity_breakdown is None:
        severity_breakdown = {}
        for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
            severity_breakdown[sev] = 0
        for f in findings:
            sev = (f.get("severity") or "INFO").upper()
            if sev in severity_breakdown:
                severity_breakdown[sev] += 1

    total_findings = sum(severity_breakdown.values())

    cards_html = _severity_cards(severity_breakdown)
    cwe_html = _cwe_section(severity_breakdown, findings)
    compliance_html = _compliance_overview(severity_breakdown, findings)
    findings_html = _findings_rows(findings)

    executive_summary_html = ""
    if executive_summary:
        executive_summary_html = (
            f"<h2>📋 Executive Summary</h2>"
            f'<div class="summary">{_escape(executive_summary)}</div>'
        )

    return _HTML_TEMPLATE.format(
        title=_escape(title),
        target=_escape(target),
        scan_date=_escape(scan_date),
        total_findings=total_findings,
        severity_cards=cards_html,
        cwe_section=cwe_html,
        compliance_section=compliance_html,
        executive_summary_html=executive_summary_html,
        findings_rows=findings_html,
    )
