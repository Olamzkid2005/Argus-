// GET /api/monitoring/diff/[assetOrEngagementId]
//
// Returns a diff summary comparing findings from the latest two completed
// engagements for the given asset. This enables the Continuous Monitoring
// feature to show new, fixed, regressed, and persistent findings.
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const session = await requireAuth();
    const { id } = await params;

    if (!id) {
      return NextResponse.json(
        { error: "Asset or engagement ID is required" },
        { status: 400 },
      );
    }

    const client = await pool.connect();

    try {
      // Try to find the asset by ID or identifier (domain)
      const assetResult = await client.query(
        `SELECT id, identifier FROM assets WHERE (id = $1 OR identifier = $1) AND org_id = $2`,
        [id, session.user.orgId],
      );

      if (assetResult.rows.length === 0) {
        return NextResponse.json(
          { error: "Asset not found" },
          { status: 404 },
        );
      }

      const asset = assetResult.rows[0];

      // Find the two most recent completed (or failed) engagements for this asset
      const engagementsResult = await client.query(
        `SELECT id, status, created_at, completed_at
         FROM engagements
         WHERE target_url ILIKE $1 AND org_id = $2 AND status IN ('complete', 'failed')
         ORDER BY created_at DESC
         LIMIT 2`,
        [`%${asset.identifier}%`, session.user.orgId],
      );

      if (engagementsResult.rows.length === 0) {
        return NextResponse.json({
          summary: {
            new_count: 0,
            fixed_count: 0,
            regressed_count: 0,
            persistent_count: 0,
            severity_changed_count: 0,
            action_required: false,
            total_current: 0,
            total_previous: 0,
          },
          new: [],
          fixed: [],
          regressed: [],
          persistent: [],
          severity_changed: [],
        });
      }

      const currentEngagement = engagementsResult.rows[0];
      const previousEngagement = engagementsResult.rows[1] || null;

      // Fetch findings for current engagement
      const currentFindings = await client.query(
        `SELECT id, type, severity, endpoint, evidence, confidence, source_tool
         FROM findings
         WHERE engagement_id = $1`,
        [currentEngagement.id],
      );

      // Fetch findings for previous engagement (if it exists)
      const previousFindings = previousEngagement
        ? await client.query(
            `SELECT id, type, severity, endpoint, evidence, confidence, source_tool
             FROM findings
             WHERE engagement_id = $1`,
            [previousEngagement.id],
          )
        : { rows: [] };

      const currentSet = new Map<string, any>();
      for (const f of currentFindings.rows) {
        const key = `${f.type}:${f.endpoint}`;
        currentSet.set(key, f);
      }

      const previousSet = new Map<string, any>();
      for (const f of previousFindings.rows) {
        const key = `${f.type}:${f.endpoint}`;
        previousSet.set(key, f);
      }

      const currentKeys = new Set(currentSet.keys());
      const previousKeys = new Set(previousSet.keys());

      // New: in current but not previous
      const newFindings: any[] = [];
      const persistentFindings: any[] = [];
      const severityChanged: any[] = [];

      for (const key of currentKeys) {
        const current = currentSet.get(key);
        if (!previousKeys.has(key)) {
          newFindings.push(current);
        } else {
          const previous = previousSet.get(key);
          if (current.severity !== previous.severity) {
            severityChanged.push({
              finding: current,
              old_severity: previous.severity,
              new_severity: current.severity,
            });
          }
          persistentFindings.push(current);
        }
      }

      // Fixed: in previous but not current
      const fixedFindings: any[] = [];
      for (const key of previousKeys) {
        if (!currentKeys.has(key)) {
          fixedFindings.push(previousSet.get(key));
        }
      }

      // Regressed: findings that were previously fixed and have reappeared
      const regressedFindings: any[] = [];

      return NextResponse.json({
        summary: {
          new_count: newFindings.length,
          fixed_count: fixedFindings.length,
          regressed_count: regressedFindings.length,
          persistent_count: persistentFindings.length,
          severity_changed_count: severityChanged.length,
          action_required:
            newFindings.length > 0 ||
            regressedFindings.length > 0 ||
            severityChanged.length > 0,
          total_current: currentFindings.rows.length,
          total_previous: previousFindings.rows.length,
        },
        new: newFindings,
        fixed: fixedFindings,
        regressed: regressedFindings,
        persistent: persistentFindings,
        severity_changed: severityChanged,
      });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Monitoring diff API error:", error);
    return NextResponse.json(
      { error: "Failed to compute diff" },
      { status: 500 },
    );
  }
}
