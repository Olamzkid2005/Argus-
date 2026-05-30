import crypto from "crypto";
import { NextResponse } from "next/server";

export interface ApiErrorResponse {
  error: string;
  code: string;
  details?: Record<string, string>;
  requestId?: string;
}

function generateRequestId(): string {
  return crypto.randomUUID();
}

/**
 * Create a standardized error response with sanitized details.
 *
 * Sensitive information (stack traces, SQL queries, internal paths) is
 * stripped from `details` before being sent to the client. Only safe,
 * pre-approved key-value pairs should be passed as details.
 */
export function createErrorResponse(
  error: string,
  code: string,
  details?: Record<string, string>,
  statusCode: number = 500,
): Response {
  const body: ApiErrorResponse = {
    error,
    code,
    requestId: generateRequestId(),
  };
  // Only include sanitized details — strip any values that look sensitive
  if (details) {
    const sanitized: Record<string, string> = {};
    for (const [key, value] of Object.entries(details)) {
      // Block known sensitive key patterns
      const sensitiveKeys = /^(password|secret|token|key|credential|auth|certificate|private)/i;
      if (sensitiveKeys.test(key)) continue;
      // Truncate long values to prevent data leakage
      sanitized[key] = value.length > 200 ? value.slice(0, 200) + "..." : value;
    }
    if (Object.keys(sanitized).length > 0) {
      body.details = sanitized;
    }
  }
  return NextResponse.json(body, { status: statusCode });
}

export const ErrorCodes = {
  UNAUTHORIZED: "UNAUTHORIZED",
  FORBIDDEN: "FORBIDDEN",
  NOT_FOUND: "NOT_FOUND",
  VALIDATION_ERROR: "VALIDATION_ERROR",
  RATE_LIMITED: "RATE_LIMITED",
  INTERNAL_ERROR: "INTERNAL_ERROR",
  BAD_REQUEST: "BAD_REQUEST",
} as const;
