import { NextResponse } from "next/server";

export interface ApiErrorResponse {
  error: string;
  code: string;
  details?: any;
  requestId?: string;
}

function generateRequestId(): string {
  return crypto.randomUUID();
}

export function createErrorResponse(
  error: string,
  code: string,
  details?: any,
  statusCode: number = 500,
): Response {
  const body: ApiErrorResponse = {
    error,
    code,
    details,
    requestId: generateRequestId(),
  };
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
