import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Middleware for security headers, rate limiting, and API versioning
 */

function getClientIP(request: NextRequest): string {
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) {
    return forwarded.split(",")[0].trim();
  }
  return request.ip || "unknown";
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

  // Apply rate limiting to API routes only when Upstash is configured
  if (request.nextUrl.pathname.startsWith("/api/")) {
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

        const ratelimit = new Ratelimit({
          redis,
          limiter: Ratelimit.slidingWindow(100, "60s"),
          prefix: "ratelimit:",
        });

        const ip = getClientIP(request);
        const { success } = await ratelimit.limit(ip);

        if (!success) {
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
      } catch {
        // Rate limiting failed, continue without it
      }
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
    "camera=(), microphone=(), geolocation=()",
  );

  // Content Security Policy
  response.headers.set(
    "Content-Security-Policy",
    "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
  );

  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
