"""
PDF Report Generator — pure function for PDF security assessment reports.

Converts structured findings data into a professional PDF using fpdf2.
No file I/O — returns bytes. File writing lives in reporting/exporter.py.

Architecture (ADR-024):
    Rendering is pure (no I/O, no side effects).
    PDF bytes are written to disk by the exporter at the application boundary.

Usage:
    from reporting.pdf_report import render_pdf_report

    pdf_bytes = render_pdf_report(
        title="Security Assessment Report",
        target="https://example.com",
        findings=findings_list,
        severity_breakdown=sev_counts,
    )
    # Write to disk (in application boundary):
    Path("report.pdf").write_bytes(pdf_bytes)
"""

import datetime
import logging
from typing import Any

from tool_core._compat import utc

logger = logging.getLogger(__name__)

# Severity colors (matching html_report.py)
_SEVERITY_COLORS: dict[str, tuple[int, int, int]] = {
    "CRITICAL": (139, 0, 0),
    "HIGH": (215, 58, 74),
    "MEDIUM": (210, 153, 34),
    "LOW": (14, 138, 22),
    "INFO": (88, 166, 255),
}

_SEVERITY_ORDER = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")


def render_pdf_report(
    title: str = "Security Assessment Report",
    target: str = "",
    findings: list[dict] | None = None,
    scan_date: str | None = None,
    severity_breakdown: dict | None = None,
    executive_summary: str = "",
) -> bytes:
    """Generate a professional PDF security assessment report.

    This is a PURE function:
    - No file I/O
    - No subprocess calls
    - No side effects
    - Returns bytes ready for writing to disk

    Uses fpdf2 (no LaTeX, no system deps, pure Python).

    Args:
        title: Report title.
        target: Target URL or description.
        findings: List of finding dicts. Each should have: severity, type/finding_type,
                  endpoint, title, description, remediation, cwe_id.
        scan_date: ISO-formatted date string. Auto-generated if None.
        severity_breakdown: Dict of severity -> count. Computed if None.
        executive_summary: Free-text executive summary.

    Returns:
        PDF document as bytes.
    """
    # Lazily import fpdf2 so this module can be imported without the dependency
    try:
        from fpdf import FPDF
    except ImportError:
        logger.error(
            "fpdf2 is required for PDF report generation. "
            "Install it with: pip install fpdf2"
        )
        raise

    findings = findings or []
    scan_date = scan_date or datetime.datetime.now(utc).strftime("%Y-%m-%d %H:%M UTC")

    if severity_breakdown is None:
        severity_breakdown = {}
        for sev in _SEVERITY_ORDER:
            severity_breakdown[sev] = 0
        for f in findings:
            sev = (f.get("severity") or "INFO").upper()
            if sev in severity_breakdown:
                severity_breakdown[sev] += 1

    total_findings = sum(severity_breakdown.values())

    # Create a subclass of FPDF with footer override
    class _ReportPDF(FPDF):
        def footer(self) -> None:
            self.set_y(-15)
            self.set_font("Helvetica", "I", 7)
            self.set_text_color(88, 166, 255)
            self.cell(0, 6, f"Argus Security Assessment Platform | Page {self.page_no()}/{{nb}}", align="C")

    pdf = _ReportPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    # ── Cover Page ──────────────────────────────────────────────
    pdf.add_page()
    _draw_cover_page(pdf, title, target, scan_date, total_findings)

    # ── Severity Summary ────────────────────────────────────────
    pdf.add_page()
    _draw_severity_summary(pdf, severity_breakdown, total_findings)

    # ── Executive Summary ───────────────────────────────────────
    if executive_summary:
        pdf.add_page()
        _draw_executive_summary(pdf, executive_summary)

    # ── Findings ────────────────────────────────────────────────
    if findings:
        pdf.add_page()
        _draw_findings_table(pdf, findings)

    return bytes(pdf.output())


def _draw_cover_page(
    pdf: Any, title: str, target: str, scan_date: str, total: int
) -> None:
    """Draw the cover page with title, target, and metadata."""
    # Dark header band
    pdf.set_fill_color(13, 17, 23)
    pdf.rect(0, 0, 210, 80, "F")

    pdf.set_y(25)
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(230, 237, 243)
    pdf.cell(0, 14, "Security Assessment Report", align="C", new_x="LMARGIN", new_y="NEXT")

    # Subtitle / target
    pdf.set_font("Helvetica", "", 14)
    pdf.set_text_color(139, 148, 158)
    pdf.cell(0, 10, f"Target: {target}", align="C", new_x="LMARGIN", new_y="NEXT")

    # Separator line
    pdf.set_y(95)
    pdf.set_draw_color(48, 54, 61)
    pdf.set_line_width(0.5)
    pdf.line(30, pdf.get_y(), 180, pdf.get_y())

    # Metadata block
    pdf.set_y(110)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(139, 148, 158)
    pdf.cell(0, 8, f"Generated: {scan_date}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"Total Findings: {total}", align="C", new_x="LMARGIN", new_y="NEXT")

    # Bottom branding
    pdf.set_y(250)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(88, 166, 255)
    pdf.cell(0, 6, "Argus Security Assessment Platform", align="C", new_x="LMARGIN", new_y="NEXT")


def _draw_severity_summary(
    pdf: Any, breakdown: dict, total: int
) -> None:
    """Draw severity summary cards."""
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(230, 237, 243)
    pdf.cell(0, 14, "Severity Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Total line
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(139, 148, 158)
    pdf.cell(0, 8, f"Total findings: {total}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Severity cards — draw as bordered boxes
    card_w = 32
    card_h = 28
    gap = 4
    start_x = 18

    pdf.set_font("Helvetica", "B", 16)
    for i, sev in enumerate(_SEVERITY_ORDER):
        count = breakdown.get(sev, 0)
        x = start_x + i * (card_w + gap)
        y = pdf.get_y()

        # Card background
        r, g, b = _SEVERITY_COLORS.get(sev, (88, 166, 255))
        pdf.set_fill_color(r, g, b)
        pdf.set_draw_color(r, g, b)
        pdf.rect(x, y, card_w, card_h, "DF")

        # Count
        pdf.set_xy(x, y + 4)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(card_w, 10, str(count), align="C")

        # Severity label
        pdf.set_xy(x, y + 16)
        pdf.set_font("Helvetica", "B", 7)
        pdf.cell(card_w, 6, sev, align="C")

    pdf.ln(40)


def _draw_executive_summary(pdf: Any, summary: str) -> None:
    """Draw executive summary section."""
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(230, 237, 243)
    pdf.cell(0, 14, "Executive Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(200, 210, 220)

    # Word-wrap the summary text
    pdf.multi_cell(0, 6, summary, align="L")


def _draw_findings_table(pdf: Any, findings: list[dict]) -> None:
    """Draw findings detail table."""
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(230, 237, 243)
    pdf.cell(0, 14, "Findings Detail", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Table header
    col_widths = [18, 50, 40, 72]
    headers = ["Sev", "Type", "Endpoint", "Title"]

    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(33, 38, 45)
    pdf.set_text_color(139, 148, 158)
    pdf.set_draw_color(48, 54, 61)

    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 8, header, border=1, fill=True, align="C")
    pdf.ln()

    # Table rows
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(230, 237, 243)

    for f in findings:
        sev = (f.get("severity") or "INFO").upper()
        finding_type = f.get("finding_type") or f.get("type") or "Unknown"
        endpoint = f.get("endpoint") or "N/A"
        title = f.get("title") or finding_type

        # Truncate long fields
        if len(title) > 45:
            title = title[:42] + "..."

        row_h = 7
        y_start = pdf.get_y()

        # Check if we need a page break
        if y_start + row_h > 270:
            pdf.add_page()
            y_start = pdf.get_y()

        # Severity cell with color
        r, g, b = _SEVERITY_COLORS.get(sev, (88, 166, 255))
        pdf.set_fill_color(r, g, b)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(col_widths[0], row_h, sev[:4], border=1, fill=True, align="C")

        # Regular cells
        pdf.set_text_color(230, 237, 243)
        pdf.cell(col_widths[1], row_h, finding_type[:20], border=1)
        pdf.cell(col_widths[2], row_h, endpoint[:22], border=1)
        pdf.cell(col_widths[3], row_h, title[:40], border=1)
        pdf.ln()

        # Description and remediation as sub-row
        description = f.get("description") or ""
        remediation = f.get("remediation") or ""
        cwe = f.get("cwe_id") or ""
        has_detail = bool(description or remediation or cwe)

        if has_detail:
            detail_text = ""
            if description:
                detail_text += f"Description: {description}  "
            if cwe:
                detail_text += f"CWE: {cwe}  "
            if remediation:
                detail_text += f"Remediation: {remediation}"

            if detail_text:
                pdf.set_font("Helvetica", "I", 6)
                pdf.set_text_color(139, 148, 158)
                pdf.set_fill_color(22, 27, 34)

                # Calculate how many lines the detail text needs
                # Use a narrower width since we indent
                indent = 4
                detail_width = sum(col_widths) - indent
                lines = pdf.multi_cell(detail_width, 5, detail_text, dry_run=True, output="LINES")  # type: ignore[call-overload]
                line_count = len(lines) if lines else 1

                # Draw background and write detail
                sub_row_h = max(6, line_count * 5 + 3)

                if pdf.get_y() + sub_row_h > 270:
                    pdf.add_page()

                # Fill background
                pdf.set_fill_color(22, 27, 34)
                pdf.rect(
                    pdf.l_margin + indent,
                    pdf.get_y(),
                    sum(col_widths) - indent,
                    sub_row_h,
                    "F",
                )

                pdf.set_xy(pdf.l_margin + indent + 1, pdf.get_y() + 1)
                pdf.multi_cell(detail_width - 2, 5, detail_text)

                # Reset font
                pdf.set_font("Helvetica", "", 7)
                pdf.set_text_color(230, 237, 243)

    # Summary footer after findings table
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(139, 148, 158)
    pdf.cell(0, 6, "End of findings report.", align="C", new_x="LMARGIN", new_y="NEXT")


# Footer is now handled by the _ReportPDF.footer() override above.
