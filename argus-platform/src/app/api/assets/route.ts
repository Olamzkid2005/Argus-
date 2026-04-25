// Asset Inventory API route
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function GET(req: NextRequest) {
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);

    const assetType = searchParams.get("type");
    const lifecycle = searchParams.get("lifecycle") || "active";
    const riskLevel = searchParams.get("risk_level");
    const limit = parseInt(searchParams.get("limit") || "50");
    const offset = parseInt(searchParams.get("offset") || "0");

    const client = await pool.connect();

    try {
      let query = `
        SELECT id, asset_type, identifier, display_name, description, attributes, risk_score, risk_level, criticality, lifecycle_status, discovered_at, last_scanned_at, verified, created_at
        FROM assets
        WHERE org_id = $1
      `;
      const params: unknown[] = [session.user.orgId];
      let paramIndex = 2;

      if (assetType && assetType !== "all") {
        query += ` AND asset_type = $${paramIndex}`;
        params.push(assetType);
        paramIndex++;
      }

      if (lifecycle && lifecycle !== "all") {
        query += ` AND lifecycle_status = $${paramIndex}`;
        params.push(lifecycle);
        paramIndex++;
      }

      if (riskLevel && riskLevel !== "all") {
        query += ` AND risk_level = $${paramIndex}`;
        params.push(riskLevel);
        paramIndex++;
      }

      query += ` ORDER BY risk_score DESC NULLS LAST, created_at DESC LIMIT $${paramIndex} OFFSET $${paramIndex + 1}`;
      params.push(limit, offset);

      const result = await client.query(query, params);

      // Get summary stats
      let statsQuery = `
        SELECT 
          COUNT(*) as total,
          COUNT(*) FILTER (WHERE risk_level = 'CRITICAL') as critical,
          COUNT(*) FILTER (WHERE risk_level = 'HIGH') as high,
          COUNT(*) FILTER (WHERE lifecycle_status = 'active') as active
        FROM assets
        WHERE org_id = $1
      `;
      const statsParams: unknown[] = [session.user.orgId];

      if (assetType && assetType !== "all") {
        statsQuery += ` AND asset_type = $2`;
        statsParams.push(assetType);
      }

      const statsResult = await client.query(statsQuery, statsParams);

      return NextResponse.json({
        assets: result.rows,
        stats: statsResult.rows[0],
      });
    } finally {
      client.release();
    }
  } catch (error) {
    const err = error as Error;
    console.error("Assets API error:", err.message);
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    // Detect common DB schema issue
    if (err.message?.includes("relation") && err.message?.includes("does not exist")) {
      return NextResponse.json({
        error: "Asset inventory table not found. Run '011_add_assets_table.sql' migration.",
      }, { status: 500 });
    }
    return NextResponse.json({ error: "Failed to fetch assets" }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const session = await requireAuth();
    const body = await req.json();

    const { asset_type, identifier, display_name, description, attributes, criticality } = body;

    if (!asset_type || !identifier) {
      return NextResponse.json(
        { error: "asset_type and identifier are required" },
        { status: 400 },
      );
    }

    const client = await pool.connect();

    try {
      const result = await client.query(
        `
        INSERT INTO assets (org_id, asset_type, identifier, display_name, description, attributes, criticality, lifecycle_status)
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'active')
        RETURNING id, asset_type, identifier, risk_score, risk_level, lifecycle_status, created_at
        `,
        [
          session.user.orgId,
          asset_type,
          identifier,
          display_name || identifier,
          description || "",
          JSON.stringify(attributes || {}),
          criticality || "medium",
        ],
      );

      return NextResponse.json({ asset: result.rows[0] }, { status: 201 });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Create asset error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to create asset" }, { status: 500 });
  }
}
