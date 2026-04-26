// Stop engagement API route
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { requireEngagementAccess } from "@/lib/authorization";
import { pool } from "@/lib/db";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const session = await requireAuth();
    const { id: engagementId } = await params;

    // Verify user has access to this engagement
    await requireEngagementAccess(session, engagementId);

    const client = await pool.connect();

    try {
      // Get current status
      const statusCheck = await client.query(
        "SELECT status FROM engagements WHERE id = $1",
        [engagementId],
      );

      if (statusCheck.rowCount === 0) {
        return NextResponse.json(
          { error: "Engagement not found" },
          { status: 404 },
        );
      }

      const currentStatus = statusCheck.rows[0].status;

      // Only allow stopping in-progress engagements
      const stoppableStates = ["created", "recon", "awaiting_approval", "scanning", "analyzing", "reporting"];
      if (!stoppableStates.includes(currentStatus)) {
        return NextResponse.json(
          { error: `Cannot stop engagement with status: ${currentStatus}` },
          { status: 400 },
        );
      }

      // Update status to 'failed' (representing stopped)
      await client.query(
        "UPDATE engagements SET status = 'failed', completed_at = NOW() WHERE id = $1",
        [engagementId],
      );

      // Update Redis state if applicable
      try {
        const Redis = (await import("ioredis")).default;
        const redis = new Redis(process.env.REDIS_URL || "redis://localhost:6379");
        const stateKey = `state:engagement:${engagementId}`;
        await redis.set(stateKey, "failed");
        await redis.expire(stateKey, 300);
        await redis.quit();
      } catch (redisErr) {
        console.warn("Failed to update Redis state:", redisErr);
      }

      return NextResponse.json({ success: true, status: "failed" });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Stop engagement error:", error);
    const err = error as Error;

    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    if (err.message.startsWith("Forbidden")) {
      return NextResponse.json({ error: err.message }, { status: 403 });
    }

    return NextResponse.json(
      { error: "Failed to stop engagement" },
      { status: 500 },
    );
  }
}
