// Activity feed and notifications API
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

export async function GET(req: NextRequest) {
  log.api('GET', '/api/collaboration/activity', { query: req.nextUrl.search });
  try {
    const session = await requireAuth();
    const { searchParams } = new URL(req.url);
    const type = searchParams.get("type");
    const limit = Math.min(parseInt(searchParams.get("limit") || "50", 10), 100);
    const offset = parseInt(searchParams.get("offset") || "0", 10);

    // Fetch activity feed
    let activityQuery = `
      SELECT af.id, af.activity_type, af.description, af.metadata, af.created_at,
             u.email as user_email, u.name as user_name
      FROM activity_feed af
      LEFT JOIN users u ON af.user_id = u.id
      WHERE af.org_id = $1
    `;
    const activityParams: unknown[] = [session.user.orgId];

    if (type) {
      activityQuery += ` AND af.activity_type = $${activityParams.length + 1}`;
      activityParams.push(type);
    }

    activityQuery += ` ORDER BY af.created_at DESC LIMIT $${activityParams.length + 1} OFFSET $${activityParams.length + 2}`;
    activityParams.push(limit, offset);

    const activityResult = await pool.query(activityQuery, activityParams);

    // Fetch unread notifications for current user
    const notificationsResult = await pool.query(
      `
      SELECT id, type, title, message, entity_type, entity_id, is_read, created_at
      FROM notifications
      WHERE user_id = $1
      ORDER BY created_at DESC
      LIMIT 20
      `,
      [session.user.id],
    );

    const unreadCount = await pool.query(
      `SELECT COUNT(*) FROM notifications WHERE user_id = $1 AND is_read = false`,
      [session.user.id],
    );

    log.apiEnd('GET', '/api/collaboration/activity', 200, { activityCount: activityResult.rows.length });
    return NextResponse.json({
      activities: activityResult.rows,
      notifications: notificationsResult.rows,
      unread_count: parseInt(unreadCount.rows[0].count),
    });
  } catch (error) {
    log.error("Get activity feed error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    const detail = process.env.NODE_ENV === "development" ? err.message : "Failed to fetch activity feed";
    return NextResponse.json({ error: detail }, { status: 500 });
  }
}

export async function PATCH(req: NextRequest) {
  log.api('PATCH', '/api/collaboration/activity');
  try {
    const session = await requireAuth();
    const body = await req.json();
    const { notification_ids, mark_all_read } = body;

    if (mark_all_read) {
      await pool.query(
        `UPDATE notifications SET is_read = true WHERE user_id = $1`,
        [session.user.id],
      );
    } else if (notification_ids && Array.isArray(notification_ids)) {
      await pool.query(
        `UPDATE notifications SET is_read = true WHERE id = ANY($1) AND user_id = $2`,
        [notification_ids, session.user.id],
      );
    }

    log.apiEnd('PATCH', '/api/collaboration/activity', 200);
    return NextResponse.json({ success: true });
  } catch (error) {
    log.error("Update notifications error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to update notifications" }, { status: 500 });
  }
}
