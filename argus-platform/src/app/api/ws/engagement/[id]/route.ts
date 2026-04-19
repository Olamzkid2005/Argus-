/**
 * WebSocket Endpoint for Real-Time Engagement Updates
 *
 * This endpoint handles WebSocket connections for real-time updates
 * on engagement progress, findings, and state transitions.
 *
 * Requirements: 31.1
 */

import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { requireEngagementAccess } from "@/lib/authorization";
import { WEBSOCKET_CHANNELS } from "@/lib/websocket-events";

// WebSocket upgrade is not natively supported in Next.js App Router
// This implementation provides a polling-based fallback with instructions
// for production WebSocket setup

/**
 * GET handler for WebSocket upgrade and polling fallback
 *
 * For production WebSocket support, use a custom server or:
 * - Socket.io with Next.js custom server
 * - Pusher or Ably for managed WebSocket service
 * - Vercel Edge Functions with WebSocket support
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

    // Check if this is a WebSocket upgrade request
    const upgradeHeader = req.headers.get("upgrade");

    if (upgradeHeader && upgradeHeader.toLowerCase() === "websocket") {
      // WebSocket upgrade not supported in standard Next.js App Router
      // Return instructions for WebSocket setup
      return new NextResponse(
        JSON.stringify({
          error: "WebSocket upgrade not supported",
          message: "Use polling endpoint or configure custom WebSocket server",
          pollingEndpoint: `/api/ws/engagement/${engagementId}/poll`,
          instructions: "See documentation for WebSocket setup options",
        }),
        {
          status: 426,
          headers: { "Content-Type": "application/json" },
        },
      );
    }

    // Return connection info for client-side polling
    return NextResponse.json({
      status: "ready",
      engagement_id: engagementId,
      polling_endpoint: `/api/ws/engagement/${engagementId}/poll`,
      channels: [WEBSOCKET_CHANNELS.engagement(engagementId)],
      message: "Use polling endpoint for real-time updates",
    });
  } catch (error: unknown) {
    console.error("WebSocket endpoint error:", error);
    const err = error as Error;

    if (err.message === "Unauthorized") {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }

    if (err.message.startsWith("Forbidden")) {
      return NextResponse.json({ error: err.message }, { status: 403 });
    }

    return NextResponse.json(
      { error: "Failed to establish connection" },
      { status: 500 },
    );
  }
}
