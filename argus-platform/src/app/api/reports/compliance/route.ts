// Compliance reports API
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

export async function GET(req: NextRequest) {
  log.api('GET', '/api/reports/compliance', { query: req.nextUrl.search });
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);
    const engagementId = searchParams.get("engagement_id");

    const client = await pool.connect();

    try {
      let query = `
        SELECT cr.id, cr.engagement_id, cr.standard, cr.title, cr.status, cr.created_at, cr.updated_at
        FROM compliance_reports cr
        JOIN engagements e ON cr.engagement_id = e.id
        WHERE e.org_id = $1
      `;
      const params: unknown[] = [session.user.orgId];

      if (engagementId && engagementId !== "all") {
        query += ` AND cr.engagement_id = $2`;
        params.push(engagementId);
      }

      query += ` ORDER BY cr.created_at DESC`;

      const result = await client.query(query, params);
      log.apiEnd('GET', '/api/reports/compliance', 200, { count: result.rows.length });
      return NextResponse.json({ reports: result.rows });
    } finally {
      client.release();
    }
  } catch (error) {
    log.error("Compliance reports API error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to fetch compliance reports" },
      { status: 500 },
    );
  }
}

export async function POST(req: NextRequest) {
  log.api('POST', '/api/reports/compliance');
  try {
    const session = await requireAuth();
    const body = await req.json();
    const { engagement_id, standard } = body;
    log.api('POST', '/api/reports/compliance', { engagement_id, standard });

    if (!engagement_id || !standard) {
      return NextResponse.json(
        { error: "engagement_id and standard are required" },
        { status: 400 },
      );
    }

    const validStandards = ["owasp_top10", "pci_dss", "soc2"];
    if (!validStandards.includes(standard)) {
      return NextResponse.json(
        { error: `standard must be one of: ${validStandards.join(", ")}` },
        { status: 400 },
      );
    }

    const client = await pool.connect();

    try {
      // Verify engagement belongs to user's org
      const verifyResult = await client.query(
        `SELECT id FROM engagements WHERE id = $1 AND org_id = $2`,
        [engagement_id, session.user.orgId],
      );

      if (verifyResult.rows.length === 0) {
        return NextResponse.json(
          { error: "Engagement not found or access denied" },
          { status: 403 },
        );
      }

      // Insert placeholder report with generating status
      const insertResult = await client.query(
        `
        INSERT INTO compliance_reports (engagement_id, standard, title, report_data, status)
        VALUES ($1, $2, $3, '{}', 'generating')
        RETURNING id
        `,
        [
          engagement_id,
          standard,
          `${standard.toUpperCase()} Compliance Report - ${engagement_id}`,
        ],
      );

      const reportId = insertResult.rows[0].id;

      // Trigger Celery task for background generation
      const { pushJob } = await import("@/lib/redis");
      await pushJob({
        type: "compliance_report",
        engagement_id: engagement_id,
        target: "",
        standard: standard,
        budget: { max_cycles: 1, max_depth: 1 },
        trace_id: "",
        created_at: new Date().toISOString(),
      });

      log.apiEnd('POST', '/api/reports/compliance', 200, { reportId, engagement_id, standard });
      return NextResponse.json({
        report_id: reportId,
        status: "generating",
        message: "Compliance report generation started",
      });
    } finally {
      client.release();
    }
  } catch (error) {
    log.error("Create compliance report error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to create compliance report" },
      { status: 500 },
    );
  }
}
