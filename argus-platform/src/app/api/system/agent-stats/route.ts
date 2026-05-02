// GET /api/system/agent-stats - Agent decision statistics for system health
import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

interface AgentStats {
  total_decisions: number;
  total_cost_usd: number;
  fallback_count: number;
  llm_count: number;
}

interface AgentDecision {
  id: string;
  engagement_id: string;
  tool_selected: string;
  reasoning: string;
  was_fallback: boolean;
  cost_usd: number;
  created_at: string;
}

/**
 * GET /api/system/agent-stats
 *
 * Returns agent decision stats for the System Health page.
 * Queries the agent_decisions table directly.
 */
export async function GET() {
  log.api("GET", "/api/system/agent-stats");
  try {
    const session = await requireAuth();

    const client = await pool.connect();
    try {
      // Aggregate stats
      const statsResult = await client.query(
        `SELECT
           COUNT(*)::int AS total_decisions,
           COALESCE(SUM(cost_usd), 0)::numeric(8,6) AS total_cost_usd,
           COUNT(*) FILTER (WHERE was_fallback = true)::int AS fallback_count,
           COUNT(*) FILTER (WHERE was_fallback = false)::int AS llm_count
         FROM agent_decisions ad
         JOIN engagements e ON ad.engagement_id = e.id
         WHERE e.org_id = $1`,
        [session.user.orgId],
      );
      const stats: AgentStats = {
        total_decisions: parseInt(statsResult.rows[0]?.total_decisions) || 0,
        total_cost_usd: parseFloat(statsResult.rows[0]?.total_cost_usd) || 0,
        fallback_count: parseInt(statsResult.rows[0]?.fallback_count) || 0,
        llm_count: parseInt(statsResult.rows[0]?.llm_count) || 0,
      };

      // Recent 10 decisions
      const recentResult = await client.query(
        `SELECT id, engagement_id, tool_selected, reasoning, was_fallback, cost_usd, created_at
         FROM agent_decisions ad
         JOIN engagements e ON ad.engagement_id = e.id
         WHERE e.org_id = $1
         ORDER BY ad.created_at DESC
         LIMIT 10`,
        [session.user.orgId],
      );
      const recent_decisions: AgentDecision[] = recentResult.rows.map((r) => ({
        id: r.id,
        engagement_id: r.engagement_id,
        tool_selected: r.tool_selected,
        reasoning: r.reasoning || "",
        was_fallback: r.was_fallback,
        cost_usd: parseFloat(r.cost_usd) || 0,
        created_at: r.created_at,
      }));

      log.apiEnd("GET", "/api/system/agent-stats", 200, {
        total: stats.total_decisions,
      });
      return NextResponse.json({
        data: stats,
        recent_decisions,
      });
    } finally {
      client.release();
    }
  } catch (error) {
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    log.error("Agent stats error:", err.message || String(err));
    return NextResponse.json(
      { error: "Failed to fetch agent stats" },
      { status: 500 }
    );
  }
}
