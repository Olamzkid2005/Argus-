// Circuit breaker status endpoint
import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { log } from "@/lib/logger";

interface CircuitBreakerTool {
  name: string;
  state: "closed" | "open" | "half_open";
  failures: number;
  last_failure: string | null;
  cooldown_remaining: number;
}

/**
 * GET /api/system/circuit-breaker
 *
 * Returns circuit breaker status for all registered tools.
 * Mock data — in production, proxy to Python backend's tools/circuit_breaker.py get_status().
 */
export async function GET() {
  await requireAuth();
  log.api("GET", "/api/system/circuit-breaker");
  try {
    const tools: CircuitBreakerTool[] = [
      {
        name: "nmap",
        state: "closed",
        failures: 0,
        last_failure: null,
        cooldown_remaining: 0,
      },
      {
        name: "nuclei",
        state: "closed",
        failures: 0,
        last_failure: null,
        cooldown_remaining: 0,
      },
      {
        name: "subfinder",
        state: "half_open",
        failures: 2,
        last_failure: new Date(Date.now() - 30_000).toISOString(),
        cooldown_remaining: 15,
      },
      {
        name: "httpx",
        state: "closed",
        failures: 0,
        last_failure: null,
        cooldown_remaining: 0,
      },
      {
        name: "amass",
        state: "open",
        failures: 5,
        last_failure: new Date(Date.now() - 5_000).toISOString(),
        cooldown_remaining: 55,
      },
    ];

    log.apiEnd("GET", "/api/system/circuit-breaker", 200);
    return NextResponse.json({ data: { tools } });
  } catch (error) {
    log.error("Circuit breaker status error:", error);
    return NextResponse.json(
      { error: "Failed to fetch circuit breaker status" },
      { status: 500 }
    );
  }
}
