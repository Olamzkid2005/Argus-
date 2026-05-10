import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { log } from "@/lib/logger";
import { pool } from "@/lib/db";

interface ToolHealthData {
  tool_name: string;
  success_rate_24h: number;
  avg_duration_seconds: number;
  total_runs_24h: number;
  last_success_at: string | null;
  consecutive_failures: number;
  status: string;
}

export async function GET() {
  log.api("GET", "/api/system/health");
  try {
    await requireAuth();
  } catch {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    let dbStatus = { status: "healthy", detail: "Connected" };
    let redisStatus = { status: "healthy", detail: "Connected" };
    let workerStatus = { status: "healthy", detail: "All workers online" };
    let circuitBreakers: Record<string, Record<string, unknown>> = {};
    let llmUsage = null;
    let toolHealth: ToolHealthData[] = [];

    // Check database
    try {
      const client = await pool.connect();
      await client.query("SELECT 1");
      client.release();
    } catch {
      dbStatus = { status: "degraded", detail: "Connection failed" };
    }

    // Check Redis
    try {
      const redis = (await import("@/lib/redis")).default;
      await redis.ping();
    } catch {
      redisStatus = { status: "degraded", detail: "Connection failed" };
    }

    // Check worker health via Redis heartbeat inspection
    try {
      const redis = (await import("@/lib/redis")).default;
      const queueLength = await redis.llen("argus:queue:celery");
      const workerKeys = await redis.keys("worker:health:*");
      if (workerKeys.length === 0) {
        workerStatus = { status: "degraded", detail: "No workers registered" };
      } else {
        workerStatus = { status: "healthy", detail: `${workerKeys.length} worker(s) online` };
      }
    } catch {
      workerStatus = { status: "degraded", detail: "Worker check failed" };
    }

    // Tool health from tool_metrics table
    if (dbStatus.status === "healthy") {
      try {
        const client = await pool.connect();
        const cutoff = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

        const result = await client.query(`
          SELECT
            tool_name,
            COUNT(*)::int AS total_runs,
            ROUND(SUM(CASE WHEN success THEN 1 ELSE 0 END)::float / NULLIF(COUNT(*), 0), 3) AS success_rate,
            ROUND(AVG(duration_ms)::float / 1000.0, 2) AS avg_duration_seconds,
            MAX(CASE WHEN success THEN created_at ELSE NULL END) AS last_success_at
          FROM tool_metrics
          WHERE created_at >= $1
          GROUP BY tool_name
          ORDER BY tool_name
        `, [cutoff]);
        client.release();

        toolHealth = (result.rows || []).map((row: Record<string, unknown>) => {
          const successRate = parseFloat(String(row.success_rate || "0"));
          const consecutiveFailures = 0;
          let status = "healthy";
          if (successRate < 0.5) status = "down";
          else if (successRate < 0.8) status = "degraded";
          return {
            tool_name: row.tool_name as string,
            success_rate_24h: successRate,
            avg_duration_seconds: parseFloat(String(row.avg_duration_seconds || "0")),
            total_runs_24h: parseInt(String(row.total_runs || "0")),
            last_success_at: row.last_success_at ? new Date(row.last_success_at as string).toISOString() : null,
            consecutive_failures: consecutiveFailures,
            status,
          };
        });
      } catch (e) {
        log.error("Tool health query failed:", (e as Error).message);
      }
    }

    // Circuit breaker data from dedicated endpoint
    try {
      const cbRes = await fetch(new URL("/api/system/circuit-breaker", process.env.NEXTAUTH_URL || "http://localhost:3000").href);
      if (cbRes.ok) {
        const cbData = await cbRes.json();
        const tools = cbData?.data?.tools || [];
        for (const tool of tools) {
          circuitBreakers[tool.name] = {
            state: tool.state || "closed",
            failure_count: tool.failures || 0,
            cooldown_remaining: tool.cooldown_remaining || 0,
            last_failure: tool.last_failure || null,
          };
        }
      }
    } catch {
      circuitBreakers = {};
    }

    // LLM usage data from dedicated endpoint
    try {
      const llmRes = await fetch(new URL("/api/system/llm-usage", process.env.NEXTAUTH_URL || "http://localhost:3000").href);
      if (llmRes.ok) {
        llmUsage = await llmRes.json();
      }
    } catch {
      llmUsage = null;
    }

    log.apiEnd("GET", "/api/system/health", 200);
    return NextResponse.json({
      database: dbStatus,
      redis: redisStatus,
      workers: workerStatus,
      circuit_breakers: circuitBreakers,
      llm_usage: llmUsage,
      tool_health: toolHealth,
    });
  } catch (error) {
    const err = error as Error;
    log.error("System health error:", err.message || String(err));
    return NextResponse.json(
      { error: "Failed to fetch system health" },
      { status: 500 }
    );
  }
}
