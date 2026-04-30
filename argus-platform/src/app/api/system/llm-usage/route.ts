// LLM usage and cost tracking endpoint
import { NextResponse } from "next/server";
import { log } from "@/lib/logger";

interface ModelUsage {
  name: string;
  calls: number;
  tokens: number;
  cost: number;
}

/**
 * GET /api/system/llm-usage
 *
 * Returns LLM token usage and cost breakdown by model.
 * Mock data — in production, proxy to Python backend usage tracker.
 */
export async function GET() {
  log.api("GET", "/api/system/llm-usage");
  try {
    const models: ModelUsage[] = [
      { name: "gpt-4o", calls: 142, tokens: 284_000, cost: 5.68 },
      { name: "gpt-4o-mini", calls: 573, tokens: 1_146_000, cost: 0.34 },
      { name: "claude-3-5-sonnet", calls: 87, tokens: 174_000, cost: 1.74 },
    ];

    const total_tokens = models.reduce((sum, m) => sum + m.tokens, 0);
    const total_cost = models.reduce((sum, m) => sum + m.cost, 0);
    const budget_max = 50.0;
    const budget_remaining = Math.max(0, budget_max - total_cost);

    log.apiEnd("GET", "/api/system/llm-usage", 200);
    return NextResponse.json({
      data: {
        total_tokens,
        total_cost: Math.round(total_cost * 100) / 100,
        models,
        budget_remaining: Math.round(budget_remaining * 100) / 100,
        budget_max,
      },
    });
  } catch (error) {
    log.error("LLM usage error:", error);
    return NextResponse.json(
      { error: "Failed to fetch LLM usage" },
      { status: 500 }
    );
  }
}
