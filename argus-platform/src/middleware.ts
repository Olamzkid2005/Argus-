import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

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
  action: string,
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

  // API Version headers
  const path = request.nextUrl.pathname;
  if (path.startsWith("/api/")) {
    if (path.startsWith("/api/v2/")) {
      response.headers.set("X-API-Version", "2.0.0");
    } else if (path.startsWith("/api/v1/")) {
      response.headers.set("X-API-Version", "1.0.0");
    } else {
      response.headers.set("X-API-Version", "1.0.0");
    }
    response.headers.set("X-API-Deprecated", "false");
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

        const { success: globalSuccess } = await globalRatelimit.limit(ip);

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

    // Audit log sensitive operations
    const sensitivePaths = [
      "/api/engagement/create",
      "/api/engagement/",
      "/api/auth/",
      "/api/admin/",
    ];

    if (sensitivePaths.some((p) => path.startsWith(p))) {
      await logAuditEvent(request, `api_${request.method.toLowerCase()}`, {
        path,
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
  response.headers.set(
    "Content-Security-Policy",
    "default-src 'self'; " +
      "script-src 'self' 'unsafe-inline' 'unsafe-eval'; " +
      "style-src 'self' 'unsafe-inline'; " +
      "img-src 'self' data: https: blob:; " +
      "font-src 'self' data:; " +
      "connect-src 'self' https: wss:; " +
      "frame-ancestors 'none'; " +
      "base-uri 'self'; " +
      "form-action 'self'; " +
      "upgrade-insecure-requests;",
  );

  // Additional security headers
  response.headers.set("X-Permitted-Cross-Domain-Policies", "none");
  response.headers.set("Cross-Origin-Embedder-Policy", "require-corp");
  response.headers.set("Cross-Origin-Opener-Policy", "same-origin");
  response.headers.set("Cross-Origin-Resource-Policy", "same-origin");

  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
