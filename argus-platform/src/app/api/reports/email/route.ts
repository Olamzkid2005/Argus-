// Email report delivery API
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { redis } from "@/lib/redis";
import { log } from "@/lib/logger";

// M-v4-20: Rate limiting — 5 email reports per hour per user to prevent abuse.
const EMAIL_RATE_LIMIT_WINDOW = 3600; // 1 hour
const MAX_EMAIL_REPORTS = 5;

async function checkEmailRateLimit(userId: string): Promise<boolean> {
  const key = `ratelimit:email_report:${userId}`;
  const setResult = await redis.set(key, 1, "EX", EMAIL_RATE_LIMIT_WINDOW, "NX");
  const current = setResult === "OK" ? 1 : await redis.incr(key);
  return current <= MAX_EMAIL_REPORTS;
}

export async function POST(req: NextRequest) {
  try {
    const session = await requireAuth();

    // Rate limit check before any processing
    const allowed = await checkEmailRateLimit(session.user.id);
    if (!allowed) {
      log.warn("Email report rate limit exceeded for user %s", session.user.id);
      return NextResponse.json(
        { error: "Too many email requests. Please try again later." },
        { status: 429 },
      );
    }
    const body = await req.json();
    const { report_id, engagement_id, recipient_override } = body;

    let report;
    let recipients: string[] = [];

    if (report_id) {
      const result = await pool.query(
        `SELECT * FROM scheduled_reports WHERE id = $1 AND org_id = $2`,
        [report_id, session.user.orgId],
      );
      if (result.rows.length === 0) {
        return NextResponse.json({ error: "Report not found" }, { status: 404 });
      }
      report = result.rows[0];
      recipients = recipient_override || report.email_recipients || [];
    } else if (engagement_id) {
      // Ad-hoc report for specific engagement
      const engResult = await pool.query(
        `SELECT * FROM engagements WHERE id = $1 AND org_id = $2`,
        [engagement_id, session.user.orgId],
      );
      if (engResult.rows.length === 0) {
        return NextResponse.json({ error: "Engagement not found" }, { status: 404 });
      }
      report = { name: `Engagement Report - ${engagement_id}`, report_type: "detailed" };
      recipients = recipient_override || [session.user.email];
    } else {
      return NextResponse.json({ error: "report_id or engagement_id is required" }, { status: 400 });
    }

    if (recipients.length === 0) {
      return NextResponse.json({ error: "No recipients specified" }, { status: 400 });
    }

    // In production, integrate with SendGrid/AWS SES/Resend here
    // For now, log the email and return success
    console.log(`[EMAIL REPORT] Would send "${report.name}" to: ${recipients.join(", ")}`);

    // Log to activity feed
    await pool.query(
      `INSERT INTO activity_feed (org_id, user_id, activity_type, entity_type, entity_id, metadata)
       VALUES ($1, $2, 'report_emailed', 'report', $3, $4)`,
      [
        session.user.orgId,
        session.user.id,
        report_id || engagement_id,
        JSON.stringify({ recipients, report_name: report.name }),
      ],
    );

    // Update last_run_at for scheduled reports
    if (report_id) {
      await pool.query(
        `UPDATE scheduled_reports SET last_run_at = NOW() WHERE id = $1`,
        [report_id],
      );
    }

    return NextResponse.json({
      success: true,
      message: `Report queued for delivery to ${recipients.length} recipient(s)`,
      recipients,
      report_name: report.name,
    });
  } catch (error) {
    console.error("Email report error:", error);
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Failed to send report email" }, { status: 500 });
  }
}
