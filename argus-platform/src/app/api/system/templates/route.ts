// Prompt templates endpoint
import { NextResponse } from "next/server";
import { log } from "@/lib/logger";

interface Template {
  name: string;
  description: string;
  variables: string[];
}

/**
 * GET /api/system/templates
 *
 * Returns available prompt templates for report generation and analysis.
 * Mock data — in production, proxy to Python backend template registry.
 */
export async function GET() {
  log.api("GET", "/api/system/templates");
  try {
    const templates: Template[] = [
      {
        name: "executive_summary",
        description: "High-level executive summary of engagement findings",
        variables: ["engagement_name", "findings_count", "critical_count", "date_range"],
      },
      {
        name: "technical_report",
        description: "Detailed technical report with remediation guidance",
        variables: ["engagement_id", "findings", "assets", "methodology"],
      },
      {
        name: "finding_detail",
        description: "Individual finding detail with evidence and remediation",
        variables: ["finding_id", "title", "severity", "evidence", "remediation"],
      },
      {
        name: "recon_summary",
        description: "Reconnaissance phase results summary",
        variables: ["domain", "subdomains", "open_ports", "technologies"],
      },
      {
        name: "risk_matrix",
        description: "Risk matrix visualization data for dashboard",
        variables: ["engagement_id", "findings", "asset_criticality"],
      },
    ];

    log.apiEnd("GET", "/api/system/templates", 200);
    return NextResponse.json({ data: { templates } });
  } catch (error) {
    log.error("Templates error:", error);
    return NextResponse.json(
      { error: "Failed to fetch templates" },
      { status: 500 }
    );
  }
}
