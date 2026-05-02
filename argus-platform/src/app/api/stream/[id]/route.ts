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

export async function GET(
  req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id: engagementId } = await params;
  log.api("GET", `/api/stream/${engagementId}`);

  try {
    const session = await requireAuth();
    await requireEngagementAccess(session, engagementId);
  } catch (error) {
    const err = error as Error;
    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    return NextResponse.json(
      { error: "Forbidden" },
      { status: 403 },
    );
  }

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

      try {
        subscriber = new Redis(redisUrl);

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
          // Don't close the stream — the heartbeat keeps it alive
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
