/**
 * Polling Endpoint for Real-Time Engagement Updates
 *
 * This endpoint provides a polling-based fallback for WebSocket functionality
 * when native WebSocket is not available.
 *
 * Requirements: 31.1, 31.2, 31.3, 31.4
 */

import { NextRequest, NextResponse } from "next/server";
import Redis from "ioredis";
import { requireAuth } from "@/lib/session";
import { requireEngagementAccess } from "@/lib/authorization";
import { WEBSOCKET_CHANNELS, WebSocketEvent } from "@/lib/websocket-events";

// Redis subscriber for pub/sub
const redis = new Redis(process.env.REDIS_URL || "redis://localhost:6379");

// Store recent events in Redis with TTL for polling
const EVENTS_TTL = 300; // 5 minutes
const MAX_EVENTS_PER_ENGAGEMENT = 100;

/**
 * GET handler for polling recent events
 */
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    // Verify authentication
    const session = await requireAuth();
    const { id: engagementId } = await params;

    // Verify user has access to this engagement
    await requireEngagementAccess(session, engagementId);

    // Parse query parameters
    const { searchParams } = new URL(req.url);
    const since = searchParams.get("since");
    const cursor = searchParams.get("cursor");
    const direction = searchParams.get("direction") || "newer";
    const limit = parseInt(searchParams.get("limit") || "50", 10);

    // Fetch events from Redis
    const eventsKey = `events:engagement:${engagementId}`;
    let rawEvents: string[] = [];
    let nextCursor: string | null = null;

    if (cursor) {
      // Cursor-based pagination: find position in list and fetch from there
      const allRaw = await redis.lrange(eventsKey, 0, MAX_EVENTS_PER_ENGAGEMENT - 1);
      const cursorIndex = allRaw.findIndex((raw) => {
        try {
          const ev = JSON.parse(raw) as WebSocketEvent;
          return `${ev.type}-${ev.timestamp}` === cursor;
        } catch {
          return false;
        }
      });

      if (cursorIndex !== -1) {
        if (direction === "older") {
          rawEvents = allRaw.slice(cursorIndex + 1, cursorIndex + 1 + limit);
        } else {
          rawEvents = allRaw.slice(0, cursorIndex).reverse().slice(0, limit);
        }
      } else {
        // Cursor not found, fall back to first page
        rawEvents = allRaw.slice(0, limit);
      }
    } else {
      // No cursor: fetch first page
      rawEvents = await redis.lrange(eventsKey, 0, limit - 1);
    }

    // Parse events
    let events: WebSocketEvent[] = rawEvents
      .map((raw) => {
        try {
          return JSON.parse(raw) as WebSocketEvent;
        } catch {
          return null;
        }
      })
      .filter((e): e is WebSocketEvent => e !== null);

    // Reverse so oldest first
    events = events.reverse();

    // Filter by timestamp if provided (fallback for non-cursor clients)
    if (since && !cursor) {
      const sinceTime = new Date(since).getTime();
      events = events.filter((e) => {
        const eventTime = new Date(e.timestamp).getTime();
        return eventTime > sinceTime;
      });
    }

    // Compute next cursor from last event
    if (events.length > 0) {
      const lastEvent = events[events.length - 1];
      nextCursor = `${lastEvent.type}-${lastEvent.timestamp}`;
    }

    // Check if there are more events
    const totalEvents = await redis.llen(eventsKey);
    const hasMore = totalEvents > limit && events.length === limit;

    // Get current engagement state
    const stateKey = `state:engagement:${engagementId}`;
    const currentState = await redis.get(stateKey);

    return NextResponse.json({
      engagement_id: engagementId,
      events,
      current_state: currentState || null,
      timestamp: new Date().toISOString(),
      count: events.length,
      nextCursor,
      hasMore,
    });
  } catch (error: unknown) {
    console.error("Polling endpoint error:", error);
    const err = error as Error;

    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    if (err.message.startsWith("Forbidden")) {
      return NextResponse.json({ error: err.message }, { status: 403 });
    }

    if (err.message.startsWith("ServiceUnavailable")) {
      return NextResponse.json(
        { error: "Authorization service unavailable" },
        { status: 503 },
      );
    }

    return NextResponse.json(
      { error: "Failed to fetch events" },
      { status: 500 },
    );
  }
}

/**
 * POST handler for publishing events (used by Python workers)
 */
export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id: engagementId } = await params;

    // Verify API key for worker authentication
    const apiKey = req.headers.get("x-api-key");
    const expectedApiKey = process.env.WORKER_API_KEY;

    if (!expectedApiKey || apiKey !== expectedApiKey) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    // Parse event from request body
    const event = (await req.json()) as WebSocketEvent;

    // Validate event
    if (!event.type || !event.timestamp) {
      return NextResponse.json(
        { error: "Invalid event format" },
        { status: 400 },
      );
    }

    // Ensure engagement_id matches
    event.engagement_id = engagementId;

    // Store event in Redis list with TTL
    const eventsKey = `events:engagement:${engagementId}`;
    await redis.lpush(eventsKey, JSON.stringify(event));
    await redis.ltrim(eventsKey, 0, MAX_EVENTS_PER_ENGAGEMENT - 1);
    await redis.expire(eventsKey, EVENTS_TTL);

    // Publish to Redis channel for any active subscribers
    const channel = WEBSOCKET_CHANNELS.engagement(engagementId);
    await redis.publish(channel, JSON.stringify(event));

    // Update current state if this is a state transition event
    if (event.type === "state_transition") {
      const stateKey = `state:engagement:${engagementId}`;
      await redis.set(stateKey, (event.data as { to_state: string }).to_state);
      await redis.expire(stateKey, EVENTS_TTL);
    }

    return NextResponse.json({
      status: "published",
      event_id: `${event.type}-${Date.now()}`,
    });
  } catch (error: unknown) {
    console.error("Event publish error:", error);

    return NextResponse.json(
      { error: "Failed to publish event" },
      { status: 500 },
    );
  }
}
