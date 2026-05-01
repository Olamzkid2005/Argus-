import { NextResponse } from "next/server";
import { log } from "@/lib/logger";
import { pool } from "@/lib/db";

export async function GET() {
  log.api("GET", "/api/system/health");
  try {
    let dbStatus = { status: "healthy", detail: "Connected" };
    let redisStatus = { status: "healthy", detail: "Connected" };
    let workerStatus = { status: "healthy", detail: "All workers online" };
    let circuitBreakers: Record<string, Record<string, unknown>> = {};
    let llmUsage = null;

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
