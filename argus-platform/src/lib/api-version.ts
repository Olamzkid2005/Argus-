/**
 * API Versioning Middleware
 * 
 * Handles API versioning via URL path prefix (/api/v1/, /api/v2/)
 * and returns version info in responses.
 * 
 * Usage:
 *   - /api/v1/engagements → current API
 *   - /api/v2/engagements → new API features
 *   - Both routes work; v2 is the latest
 */

import { NextRequest, NextResponse } from "next/server";

export const API_VERSIONS = ["v1", "v2"] as const;
export const CURRENT_VERSION = "v2";

/**
 * Get version from URL path
 */
export function getVersionFromPath(pathname: string): string {
  const match = pathname.match(/^\/api\/(v\d+)/);
  return match ? match[1] : CURRENT_VERSION;
}

/**
 * Get version from Accept header
 */
export function getVersionFromHeader(accept: string | null): string | null {
  if (!accept) return null;
  const match = accept.match(/application\/vnd\.argus\.(\w+)\+json/);
  return match ? match[1] : null;
}

/**
 * Version-aware middleware for API routes
 * Adds X-API-Version header to responses
 */
export function withVersionHeaders(
  response: NextResponse,
  version: string = CURRENT_VERSION
): NextResponse {
  response.headers.set("X-API-Version", version);
  response.headers.set("X-API-Versions-Available", API_VERSIONS.join(","));
  return response;
}

/**
 * Wrapper to get current version number
 */
export function getCurrentVersion(): typeof CURRENT_VERSION {
  return CURRENT_VERSION;
}