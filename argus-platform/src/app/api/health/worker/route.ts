// Worker health and monitoring endpoint
import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import redis from "@/lib/redis";
import { log } from "@/lib/logger";

/**
 * GET /api/health/worker
 *
 * Returns worker system health status including Redis-based queue info
 */
export async function GET(req: Request) {
  await requireAuth();
  log.api('GET', '/api/health/worker');
  try {
    const { searchParams } = new URL(req.url);
    const detailed = searchParams.get("detailed") === "true";
    log.api('GET', '/api/health/worker', { detailed });

    // Get process stats
    const stats = {
      uptime: process.uptime(),
      memory: process.memoryUsage(),
      pid: process.pid,
      platform: process.platform,
      nodeVersion: process.version,
    };

    // Check Redis connection (for Celery)
    let redisStatus = "unknown";
    let queueInfo: Record<string, number> = {};

    try {
      await redis.ping();
      redisStatus = "connected";

      // Get queue lengths if detailed
      if (detailed) {
        const queueNames = [
          "recon",
          "scan",
          "analyze",
          "report",
          "repo_scan",
        ];
        for (const q of queueNames) {
          const len = await redis.llen(q);
          queueInfo[q] = len || 0;
        }
      }
    } catch {
      redisStatus = "disconnected";
    }

    const isHealthy = redisStatus === "connected";

    log.apiEnd('GET', '/api/health/worker', isHealthy ? 200 : 503, { redisStatus });
    return NextResponse.json({
      status: isHealthy ? "healthy" : "degraded",
      timestamp: new Date().toISOString(),
      node: stats,
      redis: {
        status: redisStatus,
        ...(detailed && { queues: queueInfo }),
      },
    });
  } catch (error) {
    log.error("Worker health error:", error);
    return NextResponse.json(
      { status: "unhealthy", error: "Failed to get worker stats" },
      { status: 500 }
    );
  }
}