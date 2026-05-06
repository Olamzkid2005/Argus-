// POST /api/reports/bugbounty - Generate a Bug Bounty report
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { pushJob } from "@/lib/redis";
import crypto from "crypto";
import { log } from "@/lib/logger";

export async function POST(req: NextRequest) {
  log.api('POST', '/api/reports/bugbounty');
  try {
    const session = await requireAuth();
    const body = await req.json();
    
    const { engagement_id, platform = "hackerone" } = body;
    
    if (!engagement_id) {
      return NextResponse.json(
        { error: "engagement_id is required" },
        { status: 400 }
      );
    }

    const supportedPlatforms = ["hackerone", "bugcrowd", "intigriti", "yeswehack"];
    if (!supportedPlatforms.includes(platform.toLowerCase())) {
      return NextResponse.json(
        { error: `Unsupported platform: ${platform}. Supported: ${supportedPlatforms.join(", ")}` },
        { status: 400 }
      );
    }

    // Verify engagement exists and belongs to org
    const client = await pool.connect();
    try {
      const engResult = await client.query(
        "SELECT id, target_url, status, scan_type FROM engagements WHERE id = $1 AND org_id = $2",
        [engagement_id, session.user.orgId]
      );
      
      if (engResult.rows.length === 0) {
        return NextResponse.json(
          { error: "Engagement not found" },
          { status: 404 }
        );
      }
      
      const engagement = engResult.rows[0];
      
      // Check if engagement has findings (completed or similar)
      if (engagement.status === "created" || engagement.status === "recon") {
        return NextResponse.json(
          { error: "Engagement must have findings before generating bug bounty report" },
          { status: 400 }
        );
      }

      // Generate a unique report ID
      const reportId = crypto.randomUUID();
      const outputPath = `reports/bugbounty_${platform}_${engagement_id.slice(0, 8)}.md`;

      // Trigger Celery task
      try {
        await pushJob({
          type: "bugbounty_report",
          engagement_id,
          target: engagement.target_url,
          platform: platform.toLowerCase(),
          output_path: outputPath,
          trace_id: crypto.randomUUID(),
          created_at: new Date().toISOString(),
        });
      } catch (pushError) {
        console.error("Failed to push bug bounty job to queue:", pushError);
        return NextResponse.json(
          { error: "Failed to queue bug bounty report generation" },
          { status: 500 }
        );
      }

      log.apiEnd('POST', '/api/reports/bugbounty', 200, { reportId, engagement_id, platform });
      return NextResponse.json({
        report_id: reportId,
        platform: platform.toLowerCase(),
        engagement_id,
        status: "generating",
        message: `Bug bounty report generation started for ${platform}. Report will be available shortly.`,
      });
    } finally {
      client.release();
    }
  } catch (error) {
    log.error("Bug bounty report error:", error);
    return NextResponse.json(
      { error: "Failed to generate bug bounty report" },
      { status: 500 }
    );
  }
}

// GET /api/reports/bugbounty - List available bug bounty platforms
export async function GET() {
  log.api('GET', '/api/reports/bugbounty');
  try {
    const session = await requireAuth();
    
    return NextResponse.json({
      platforms: [
        {
          id: "hackerone",
          name: "HackerOne",
          description: "HackerOne bug bounty platform report format",
          severity_tiers: { critical: "9.0-10.0", high: "7.0-8.9", medium: "4.0-6.9", low: "0.1-3.9" },
        },
        {
          id: "bugcrowd",
          name: "Bugcrowd",
          description: "Bugcrowd VRT-based bug bounty report format",
          severity_tiers: { p1: "Critical", p2: "High", p3: "Medium", p4: "Low", p5: "Informational" },
        },
        {
          id: "intigriti",
          name: "Intigriti",
          description: "Intigriti European-style bug bounty report format",
          severity_tiers: { critical: "Critical", high: "High", medium: "Medium", low: "Low" },
        },
        {
          id: "yeswehack",
          name: "YesWeHack",
          description: "YesWeHack business-focused bug bounty report format",
          severity_tiers: { critical: "Critical", high: "High", medium: "Medium", low: "Low" },
        },
      ],
      vulnerability_types: [
        "idor", "auth", "api-graphql", "ssrf", "xss", "biz-logic",
        "cors", "sqli", "nosqli", "subdomain-takeover", "csrf", "rce",
        "prototype-pollution", "http-smuggling", "ssti", "lfi", "xxe",
        "open-redirect",
      ],
    });
  } catch (error) {
    log.error("Bug bounty platforms list error:", error);
    return NextResponse.json({ platforms: [] });
  }
}
