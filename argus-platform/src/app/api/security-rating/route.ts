// Security Rating API endpoint
// Returns a 0-100% security rating based on vulnerabilities found

import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import {
  calculateSecurityRating,
  getRatingLabel,
  getRatingColor,
  getSeverityCounts,
  FindingForRating,
} from "@/lib/security-rating";

export async function GET(req: NextRequest) {
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);

    const engagementId = searchParams.get("engagement_id");

    const client = await pool.connect();

    try {
      // Build query to fetch findings for the organization
      let query = `
        SELECT f.severity, f.confidence, f.cvss_score, f.fp_likelihood, f.verified
        FROM findings f
        JOIN engagements e ON f.engagement_id = e.id
        WHERE e.org_id = $1
      `;
      const params: unknown[] = [session.user.orgId];

      // Filter by engagement if provided
      if (engagementId && engagementId !== "all") {
        query += ` AND f.engagement_id = $2`;
        params.push(engagementId);
      }

      const result = await client.query(query, params);
      const findings: FindingForRating[] = result.rows;

      // Calculate security rating
      const rating = calculateSecurityRating(findings);

      // Get additional metadata
      const severityCounts = getSeverityCounts(findings);
      const label = getRatingLabel(rating);
      const color = getRatingColor(rating);

      // Calculate total findings (excluding INFO)
      const actionableFindings = findings.filter(
        (f) => f.severity !== "INFO"
      ).length;

      return NextResponse.json({
        rating,
        label,
        color,
        total_findings: findings.length,
        actionable_findings: actionableFindings,
        severity_counts: severityCounts,
        engagement_id: engagementId || "all",
      });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Security Rating API error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Failed to calculate security rating" },
      { status: 500 }
    );
  }
}
