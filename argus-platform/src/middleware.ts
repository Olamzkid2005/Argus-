import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import type { AuditAction } from "@/lib/audit";
import { log } from "@/lib/logger";

/**
 * Middleware for security headers, rate limiting, API versioning,
 * organization-level rate limiting, and audit logging
 */

function getClientIP(request: NextRequest): string {
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) {
    return forwarded.split(",")[0].trim();
  }
  return request.ip || "unknown";
}

/**
 * Log audit event for sensitive operations
 */
async function logAuditEvent(
  request: NextRequest,
  action: AuditAction,
  details?: Record<string, unknown>
) {
  try {
    const { logAudit } = await import("@/lib/audit");
    await logAudit({
      action,
      ipAddress: getClientIP(request),
      userAgent: request.headers.get("user-agent") || undefined,
      metadata: {
        path: request.nextUrl.pathname,
        method: request.method,
        ...details,
      },
    });
  } catch {
    // Audit logging is best-effort
  }
}

export async function middleware(request: NextRequest) {
  const response = NextResponse.next();

  // Generate or extract request ID for tracing
  const requestId = request.headers.get("x-request-id") || crypto.randomUUID();
  response.headers.set("X-Request-ID", requestId);

  // API Version headers
  const path = request.nextUrl.pathname;
  if (path.startsWith("/api/")) {
    // Add default rate limit headers to all API responses
    response.headers.set("X-RateLimit-Limit", "100");
    response.headers.set("X-RateLimit-Window", "60s");

    if (path.startsWith("/api/v2/")) {
      response.headers.set("X-API-Version", "2.0.0");
    } else if (path.startsWith("/api/v1/")) {
      response.headers.set("X-API-Version", "1.0.0");
    } else {
      response.headers.set("X-API-Version", "1.0.0");
    }
    response.headers.set("X-API-Deprecated", "false");

    // CORS origin validation for production
    const origin = request.headers.get("origin");
    const allowedOrigins = process.env.ALLOWED_ORIGINS?.split(",") || [];

    // Only validate origins in production
    if (process.env.NODE_ENV === "production" && allowedOrigins.length > 0) {
      if (origin && !allowedOrigins.some((o) => o.trim() === origin)) {
        // Invalid origin - still process but don't expose CORS headers
        response.headers.set("X-Origin-Validated", "invalid");
      } else if (origin) {
        response.headers.set("X-Origin-Validated", "valid");
        response.headers.set("Access-Control-Allow-Origin", origin);
        response.headers.set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
        response.headers.set("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key");
      } else {
        response.headers.set("X-Origin-Validated", "none");
      }
    }
  }

  // Apply rate limiting to API routes
  if (path.startsWith("/api/")) {
    if (
      process.env.UPSTASH_REDIS_REST_URL &&
      process.env.UPSTASH_REDIS_REST_TOKEN
    ) {
      try {
        const { Ratelimit } = await import("@upstash/ratelimit");
        const { Redis } = await import("@upstash/redis");

        const redis = new Redis({
          url: process.env.UPSTASH_REDIS_REST_URL,
          token: process.env.UPSTASH_REDIS_REST_TOKEN,
        });

        // Global IP rate limit
        const ip = getClientIP(request);
        const globalRatelimit = new Ratelimit({
          redis,
          limiter: Ratelimit.slidingWindow(100, "60s"),
          prefix: "ratelimit:global:",
        });

        const { success: globalSuccess, limit: globalLimit, remaining: globalRemaining } = await globalRatelimit.limit(ip);

        // Set rate limit headers
        response.headers.set("X-RateLimit-Limit", String(globalLimit));
        response.headers.set("X-RateLimit-Remaining", String(globalRemaining));

        if (!globalSuccess) {
          return NextResponse.json(
            { error: "Too many requests. Please try again later." },
            {
              status: 429,
              headers: {
                "Retry-After": "60",
                "X-RateLimit-Limit": "100",
                "X-RateLimit-Remaining": "0",
              },
            },
          );
        }

        // Stricter rate limit for authentication endpoints (brute force protection)
        if (path.startsWith("/api/auth/signin") || path.startsWith("/api/auth/")) {
          const authRatelimit = new Ratelimit({
            redis,
            limiter: Ratelimit.slidingWindow(5, "60s"),
            prefix: "ratelimit:auth:",
          });

          const { success: authSuccess } = await authRatelimit.limit(ip);

          if (!authSuccess) {
            return NextResponse.json(
              { error: "Too many sign-in attempts. Please try again in 60 seconds." },
              {
                status: 429,
                headers: {
                  "Retry-After": "60",
                  "X-RateLimit-Limit": "5",
                  "X-RateLimit-Remaining": "0",
                  "X-RateLimit-Scope": "auth",
                },
              },
            );
          }
        }

        // Organization-level rate limiting
        const orgId = request.headers.get("x-org-id");
        if (orgId) {
          const orgRatelimit = new Ratelimit({
            redis,
            limiter: Ratelimit.slidingWindow(500, "60s"),
            prefix: "ratelimit:org:",
          });

          const { success: orgSuccess } = await orgRatelimit.limit(orgId);

          if (!orgSuccess) {
            return NextResponse.json(
              { error: "Organization rate limit exceeded." },
              {
                status: 429,
                headers: {
                  "Retry-After": "60",
                  "X-RateLimit-Limit": "500",
                  "X-RateLimit-Remaining": "0",
                  "X-RateLimit-Scope": "organization",
                },
              },
            );
          }
        }
      } catch {
        // Rate limiting failed, continue without it
      }
    }

    // Log API request after rate limiting (don't log rate-limited requests)
    log.api(request.method, path, { query: request.nextUrl.search });

    // Audit log sensitive operations
    const sensitivePaths = [
      "/api/engagement/create",
      "/api/engagement/",
      "/api/auth/",
      "/api/admin/",
    ];

    if (sensitivePaths.some((p) => path.startsWith(p))) {
      await logAuditEvent(request, "api_request", {
        path,
        method: request.method,
      });
    }
  }

  // Security headers (always applied)
  response.headers.set("X-DNS-Prefetch-Control", "on");
  response.headers.set(
    "Strict-Transport-Security",
    "max-age=63072000; includeSubDomains; preload",
  );
  response.headers.set("X-Frame-Options", "SAMEORIGIN");
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set(
    "Permissions-Policy",
    "camera=(), microphone=(), geolocation=(), payment=()",
  );

  // Enhanced Content Security Policy
  // In production, Next.js inline scripts need hashes; we use 'unsafe-inline'
  // as a transitional measure. 'unsafe-eval' is removed for production builds.
  const isDev = process.env.NODE_ENV === "development";
  const scriptSrc = isDev
    ? "'self' 'unsafe-inline' 'unsafe-eval'"
    : "'self' 'unsafe-inline'";

  response.headers.set(
    "Content-Security-Policy",
    "default-src 'self' data:; " +
      `script-src ${scriptSrc}; ` +
      "style-src 'self' 'unsafe-inline'; " +
      "img-src 'self' data: https: blob:; " +
      "font-src 'self' data: https://fonts.gstatic.com; " +
      "connect-src 'self' https: wss:; " +
      "frame-ancestors 'none'; " +
      "base-uri 'self'; " +
      "form-action 'self'; " +
      "upgrade-insecure-requests;",
  );

  // Additional security headers
  // Use credentialless instead of require-corp to allow CDN resources
  // (fonts.gstatic.com) without requiring CORS headers on every resource.
  response.headers.set("X-Permitted-Cross-Domain-Policies", "none");
  response.headers.set("Cross-Origin-Embedder-Policy", "credentialless");
  response.headers.set("Cross-Origin-Opener-Policy", "same-origin");
  response.headers.set("Cross-Origin-Resource-Policy", "cross-origin");

  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
