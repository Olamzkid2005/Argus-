// Verification endpoint
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  try {
    const session = await requireAuth();
    const findingId = params.id;

    const client = await pool.connect();

    try {
      // Verify the finding belongs to the user's org
      const check = await client.query(
        `
        SELECT f.id FROM findings f
        JOIN engagements e ON f.engagement_id = e.id
        WHERE f.id = $1 AND e.org_id = $2
      `,
        [findingId, session.user.orgId],
      );

      if (check.rowCount === 0) {
        return NextResponse.json(
          { error: "Finding not found" },
          { status: 404 },
        );
      }

      // Mark as verified
      await client.query("UPDATE findings SET verified = true WHERE id = $1", [
        findingId,
      ]);

      return NextResponse.json({ success: true });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Verify error:", error);
    return NextResponse.json(
      { error: "Failed to verify finding" },
      { status: 500 },
    );
  }
}
