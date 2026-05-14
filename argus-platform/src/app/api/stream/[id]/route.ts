/**
 * SSE (Server-Sent Events) Stream for Real-Time Engagement Updates
 *
 * Replaces polling with a persistent connection using ReadableStream.
 * One connection per tab = zero polling overhead.
 *
 * Falls back gracefully — the hook still has polling as a fallback.
 */

import { NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { requireEngagementAccess } from "@/lib/authorization";
import Redis from "ioredis";
import { log } from "@/lib/logger";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Track active SSE connections globally for connection limiting.
 */
const activeSseConnections = new Map<string, Set<string>>(); // engagementId -> Set<connectionId>
const MAX_CONNECTIONS_PER_ENGAGEMENT = 10;
const MAX_CONNECTIONS_PER_IP = 5;

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id: engagementId } = await params;
  log.api("GET", `/api/stream/${engagementId}`);

  // ── Connection limiting ──
  const clientIp = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    req.headers.get("x-real-ip") ||
    "unknown";
  const connectionId = `${clientIp}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;

  if (!activeSseConnections.has(engagementId)) {
    activeSseConnections.set(engagementId, new Set());
  }
  const engConnections = activeSseConnections.get(engagementId)!;
  if (engConnections.size >= MAX_CONNECTIONS_PER_ENGAGEMENT) {
    log.warn("SSE connection limit reached for engagement", { engagementId, count: engConnections.size });
    return NextResponse.json(
      { error: "Too many SSE connections for this engagement" },
      { status: 429 },
    );
  }

  // Count connections per IP across all engagements
  let ipCount = 0;
  for (const conns of activeSseConnections.values()) {
    for (const cid of conns) {
      if (cid.startsWith(clientIp)) ipCount++;
    }
  }
  if (ipCount >= MAX_CONNECTIONS_PER_IP) {
    log.warn("SSE connection limit reached for IP", { clientIp, count: ipCount });
    return NextResponse.json(
      { error: "Too many SSE connections from this IP" },
      { status: 429 },
    );
  }

  try {
    const session = await requireAuth();
    await requireEngagementAccess(session, engagementId);
  } catch (error) {
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  // Track connection AFTER auth check to prevent slot exhaustion by unauthenticated requests.
  // Note: activeSseConnections is in-memory and NOT shared across serverless instances.
  // In multi-instance deployments, use Redis-based tracking instead.
  engConnections.add(connectionId);

  const encoder = new TextEncoder();
  const redisUrl = process.env.REDIS_URL || "redis://localhost:6379";

  const stream = new ReadableStream({
    async start(controller) {
      // Send initial connection event
      controller.enqueue(
        encoder.encode(`data: ${JSON.stringify({ type: "__connected__", engagement_id: engagementId })}\n\n`),
      );

      let subscriber: Redis | null = null;
      let heartbeat: NodeJS.Timeout | null = null;
      let redisReconnectAttempts = 0;
      const MAX_REDIS_RECONNECTS = 3;

      try {
        subscriber = new Redis(redisUrl, {
          retryStrategy(times) {
            if (times > MAX_REDIS_RECONNECTS) return null; // give up
            return Math.min(times * 200, 2000); // 200ms, 400ms, 600ms
          },
          maxRetriesPerRequest: 3,
          lazyConnect: true,
        });
        await subscriber.connect();

        // Send a heartbeat every 15s to keep the connection alive
        heartbeat = setInterval(() => {
          try {
            controller.enqueue(encoder.encode(": heartbeat\n\n"));
          } catch {
            // Controller might already be closed
          }
        }, 15000);

        // Subscribe to Redis channel for this engagement
        const channel = `ws:engagement:${engagementId}`;
        await subscriber.subscribe(channel);

        subscriber.on("message", (_channel: string, message: string) => {
          try {
            controller.enqueue(encoder.encode(`data: ${message}\n\n`));
          } catch {
            // Client disconnected, stop sending
          }
        });

        subscriber.on("error", (err: Error) => {
          log.error("SSE Redis subscriber error:", err.message);
          redisReconnectAttempts++;
          if (redisReconnectAttempts > MAX_REDIS_RECONNECTS) {
            log.error("SSE Redis max reconnects reached, closing stream");
            cleanup();
          }
        });

        // Handle client disconnect
        req.signal.addEventListener("abort", () => {
          cleanup();
        });
      } catch (err) {
        const error = err as Error;
        log.error("SSE stream setup error:", error.message);
        // Send error and close
        try {
          controller.enqueue(
            encoder.encode(`data: ${JSON.stringify({ type: "error", data: { error_message: "SSE connection failed" } })}\n\n`),
          );
        } catch {
          // ignore
        }
        cleanup();
      }

      function cleanup() {
        if (heartbeat) {
          clearInterval(heartbeat);
          heartbeat = null;
        }
        if (subscriber) {
          try {
            subscriber.unsubscribe();
            subscriber.disconnect();
          } catch {
            // ignore
          }
          subscriber = null;
        }
        // Release connection tracking
        engConnections.delete(connectionId);
        if (engConnections.size === 0) {
          activeSseConnections.delete(engagementId);
        }
        try {
          controller.close();
        } catch {
          // ignore if already closed
        }
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
