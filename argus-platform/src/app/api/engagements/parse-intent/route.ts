// POST /api/engagements/parse-intent
// Body: { intent: "Scan this Node.js API for IDOR..." }
// Response: structured scan config with _fallback flag if LLM unavailable
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { createErrorResponse, ErrorCodes } from "@/lib/api/errors";

export async function POST(req: NextRequest) {
  try {
    const session = await requireAuth();
    const { intent } = await req.json();

    if (!intent || typeof intent !== "string" || !intent.trim()) {
      return createErrorResponse(
        "Intent must be a non-empty string",
        ErrorCodes.VALIDATION_ERROR,
        undefined,
        400,
      );
    }

    if (intent.length > 5000) {
      return createErrorResponse(
        "Intent too long (max 5000 characters)",
        ErrorCodes.VALIDATION_ERROR,
        undefined,
        400,
      );
    }

    // Forward to worker for intent parsing
    const workerUrl = process.env.WORKER_API_URL;
    if (!workerUrl) {
      // Fallback: regex URL extraction
      const urls = intent.match(/https?:\/\/[^\s,;)]+/g);
      if (urls && urls.length > 0) {
        return NextResponse.json({
          target_url: urls[0],
          scan_type: "url",
          aggressiveness: "default",
          agent_mode: true,
          priority_classes: [],
          intent_summary: `Scan ${urls[0]}`,
          _fallback: true,
        });
      }
      return createErrorResponse(
        "Could not parse scan intent",
        ErrorCodes.INTERNAL_ERROR,
        undefined,
        422,
      );
    }

    const response = await fetch(`${workerUrl}/api/intent/parse`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        intent,
        user_id: session.user.id,
      }),
      signal: AbortSignal.timeout(15000),
      cache: "no-store",
    });

    if (!response.ok) {
      throw new Error(`Worker returned ${response.status}`);
    }

    const result = await response.json();
    return NextResponse.json(result);

  } catch (error) {
    console.error("Parse intent error:", error);
    return createErrorResponse(
      "Failed to parse scan intent",
      ErrorCodes.INTERNAL_ERROR,
      undefined,
      500,
    );
  }
}
