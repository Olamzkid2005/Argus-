// Finding comments and annotations API
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function GET(req: NextRequest) {
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);
    const findingId = searchParams.get("finding_id");

    if (!findingId) {
      return NextResponse.json({ error: "finding_id is required" }, { status: 400 });
    }

    // Verify finding access
    const accessCheck = await pool.query(
      `SELECT 1 FROM findings f JOIN engagements e ON f.engagement_id = e.id WHERE f.id = $1 AND e.org_id = $2`,
      [findingId, session.user.orgId],
    );
    if (accessCheck.rows.length === 0) {
      return NextResponse.json({ error: "Finding not found or access denied" }, { status: 403 });
    }

    const commentsResult = await pool.query(
      `
      SELECT c.id, c.content, c.parent_id, c.created_at, c.updated_at,
             u.id as user_id, u.email, u.name
      FROM finding_comments c
      JOIN users u ON c.user_id = u.id
      WHERE c.finding_id = $1
      ORDER BY c.created_at ASC
      `,
      [findingId],
    );

    const annotationsResult = await pool.query(
      `
      SELECT a.id, a.annotation_type, a.content, a.position_data, a.created_at,
             u.id as user_id, u.email, u.name
      FROM finding_annotations a
      JOIN users u ON a.user_id = u.id
      WHERE a.finding_id = $1
      ORDER BY a.created_at ASC
      `,
      [findingId],
    );

    return NextResponse.json({
      comments: commentsResult.rows,
      annotations: annotationsResult.rows,
    });
  } catch (error) {
    console.error("Get comments error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to fetch comments" }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const session = await requireAuth();
    const body = await req.json();
    const { finding_id, content, parent_id, annotation_type, position_data } = body;

    if (!finding_id || !content) {
      return NextResponse.json({ error: "finding_id and content are required" }, { status: 400 });
    }

    // Verify finding access
    const accessCheck = await pool.query(
      `SELECT 1 FROM findings f JOIN engagements e ON f.engagement_id = e.id WHERE f.id = $1 AND e.org_id = $2`,
      [finding_id, session.user.orgId],
    );
    if (accessCheck.rows.length === 0) {
      return NextResponse.json({ error: "Finding not found or access denied" }, { status: 403 });
    }

    if (annotation_type) {
      const result = await pool.query(
        `INSERT INTO finding_annotations (finding_id, user_id, annotation_type, content, position_data)
         VALUES ($1, $2, $3, $4, $5) RETURNING *`,
        [finding_id, session.user.id, annotation_type, content, position_data ? JSON.stringify(position_data) : null],
      );
      return NextResponse.json({ annotation: result.rows[0] });
    } else {
      const result = await pool.query(
        `INSERT INTO finding_comments (finding_id, user_id, content, parent_id)
         VALUES ($1, $2, $3, $4) RETURNING *`,
        [finding_id, session.user.id, content, parent_id || null],
      );
      return NextResponse.json({ comment: result.rows[0] });
    }
  } catch (error) {
    console.error("Create comment error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to create comment" }, { status: 500 });
  }
}

export async function DELETE(req: NextRequest) {
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);
    const id = searchParams.get("id");
    const type = searchParams.get("type") || "comment";

    if (!id) {
      return NextResponse.json({ error: "ID is required" }, { status: 400 });
    }

    const table = type === "annotation" ? "finding_annotations" : "finding_comments";
    await pool.query(`DELETE FROM ${table} WHERE id = $1 AND user_id = $2`, [id, session.user.id]);

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Delete comment error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to delete comment" }, { status: 500 });
  }
}
