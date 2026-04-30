// GET /api/system/agent-stats - Agent decision statistics for system health
import { NextResponse } from "next/server";
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
 * In production, proxies to the Python backend's AgentDecisionRepository.
 */
export async function GET() {
  log.api("GET", "/api/system/agent-stats");
  try {
    // Mock data — in production, query from agent_decisions table via Python backend
    const stats: AgentStats = {
      total_decisions: 0,
      total_cost_usd: 0,
      fallback_count: 0,
      llm_count: 0,
    };
    const recent_decisions: AgentDecision[] = [];

    log.apiEnd("GET", "/api/system/agent-stats", 200);
    return NextResponse.json({
      data: stats,
      recent_decisions,
    });
  } catch (error) {
    log.error("Agent stats error:", error);
    return NextResponse.json(
      { error: "Failed to fetch agent stats" },
      { status: 500 }
    );
  }
}
