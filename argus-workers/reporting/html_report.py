"""
Self-contained HTML Report Renderer.

Pure function: takes structured report data, returns an HTML string.
No file I/O. No subprocess calls. No browser launches. No side effects.

Pattern from cve-lite-cli's renderHtmlReport().
Architecture (ADR-007): Pure renderers at library layer; side effects at CLI boundary.
"""

import datetime
from html import escape
from typing import Any

# Severity colors (GitHub-dark inspired)
_SEVERITY_STYLE: dict[str, dict[str, str]] = {
    "CRITICAL": {"bg": "#8b0000", "fg": "#ffffff", "label": "CRITICAL"},
    "HIGH": {"bg": "#d73a4a", "fg": "#ffffff", "label": "HIGH"},
    "MEDIUM": {"bg": "#d29922", "fg": "#ffffff", "label": "MEDIUM"},
    "LOW": {"bg": "#0e8a16", "fg": "#ffffff", "label": "LOW"},
    "INFO": {"bg": "#58a6ff", "fg": "#ffffff", "label": "INFO"},
}

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
  h2 {{ font-size: 20px; font-weight: 600; margin: 24px 0 12px; }}
  .meta {{ color: var(--text-muted); font-size: 14px; margin-bottom: 24px; }}
  .meta span {{ margin-right: 20px; }}

  /* Severity cards */
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

  /* Search */
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

  /* Findings table */
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
  td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); font-size: 14px; }}
  tr:hover td {{ background: var(--bg-hover); }}

  .severity-badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    color: {severity_badge_text};
  }}

  /* Finding details (expandable) */
  .finding-detail {{
    display: none;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    margin: 8px 0;
  }}
  .finding-detail.open {{ display: block; }}
  .finding-detail h4 {{ font-size: 14px; margin-bottom: 8px; color: var(--accent); }}
  .finding-detail p {{ font-size: 13px; margin-bottom: 8px; color: var(--text-muted); }}
  .finding-detail pre {{
    background: #0d1117;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px;
    font-size: 12px;
    overflow-x: auto;
    margin-bottom: 8px;
  }}
  .finding-toggle {{
    cursor: pointer;
    color: var(--accent);
    font-size: 12px;
    text-decoration: none;
    margin-left: 8px;
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
  }}
  .copy-btn:hover {{ background: #30363d; }}
  .copy-btn.copied {{ background: var(--success); border-color: var(--success); }}

  .summary {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 24px;
    font-size: 14px;
    line-height: 1.7;
  }}

  footer {{
    margin-top: 40px;
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

<h2>🔍 Findings</h2>
<input type="text" class="search-bar" id="searchInput" placeholder="Search findings by title, type, endpoint, severity..." oninput="filterFindings()">

<table id="findingsTable">
<thead>
<tr>
  <th>Severity</th>
  <th>Type</th>
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
  const el = document.getElementById(id);
  el.classList.toggle('open');
  const row = document.getElementById(id + '-row');
  if (row) {{
    row.style.display = row.style.display === 'none' ? '' : 'none';
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


def _escape(val: Any) -> str:
    """HTML-escape a value, returning empty string for None."""
    if val is None:
        return ""
    return escape(str(val))


def _severity_badge_css(severity: str) -> str:
    style = _SEVERITY_STYLE.get(severity.upper(), _SEVERITY_STYLE["INFO"])
    # Inline style for the badge span
    return f"background:{style['bg']};color:{style['fg']}"


def _severity_cards(severity_breakdown: dict | None) -> str:
    """Generate severity summary card HTML."""
    cards_html = ""
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
        count = (severity_breakdown or {}).get(sev, 0)
        style = _SEVERITY_STYLE.get(sev, _SEVERITY_STYLE["INFO"])
        cards_html += (
            f'<div class="card {sev.lower()}">'
            f'<div class="count">{count}</div>'
            f'<div class="label" style="color:{style["bg"]}">{sev}</div>'
            f"</div>\n"
        )
    return cards_html


def _findings_rows(findings: list[dict]) -> str:
    """Generate findings table rows with expandable details."""
    rows = ""
    for i, f in enumerate(findings):
        sev = (f.get("severity") or "INFO").upper()
        finding_type = _escape(f.get("finding_type") or f.get("type") or "Unknown")
        endpoint = _escape(f.get("endpoint") or "N/A")
        title = _escape(f.get("title") or finding_type)
        description = _escape(f.get("description") or "")
        remediation = _escape(f.get("remediation") or "")
        cwe = _escape(f.get("cwe") or "")
        detail_id = f"detail-{i}"

        detail_html = ""
        if description or remediation or cwe:
            parts = [
                f'<tr id="{detail_id}-row" class="finding-detail" style="display:none">',
                '<td colspan="5">',
                '<div class="finding-detail open">',
            ]
            if description:
                parts.append(f"<h4>Description</h4><p>{description}</p>")
            if cwe:
                parts.append(f"<h4>CWE</h4><p>{cwe}</p>")
            if remediation:
                parts.append(f"<h4>Remediation</h4><p>{remediation}</p>")
            if remediation:
                import json

                safe_remediation = json.dumps(remediation)
                btn_click = f"copyFix({safe_remediation}, this)"
                parts.append(
                    '<button class="copy-btn" onclick="'
                    + btn_click
                    + '">Copy Fix</button>'
                )
            parts.extend(["</div>", "</td>", "</tr>"])
            detail_html = "".join(parts)

        rows += (
            f"<tr>"
            f'<td><span class="severity-badge" style="{_severity_badge_css(sev)}">{sev}</span></td>'
            f"<td>{finding_type}</td>"
            f"<td>{endpoint}</td>"
            f"<td>{title}</td>"
            f'<td><a class="finding-toggle" onclick="toggleDetail(\'{detail_id}\')">Details</a></td>'
            f"</tr>\n"
        )
        rows += detail_html
    return rows


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

    Pattern from cve-lite-cli's renderHtmlReport().

    Args:
        title: Report title.
        target: Target URL or description.
        findings: List of finding dicts. Each should have: severity, type/finding_type,
                  endpoint, title, description, remediation, cwe.
        scan_date: ISO-formatted date string. Auto-generated if None.
        severity_breakdown: Dict of severity -> count. Computed if None.
        executive_summary: Free-text executive summary.

    Returns:
        Complete HTML string (self-contained, no external resources).
    """
    findings = findings or []
    scan_date = scan_date or datetime.datetime.now(datetime.UTC).strftime(
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

    severity_badge_text = "#ffffff"

    cards_html = _severity_cards(severity_breakdown)
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
        executive_summary_html=executive_summary_html,
        findings_rows=findings_html,
        severity_badge_text=severity_badge_text,
    )
