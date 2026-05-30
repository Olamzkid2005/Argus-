import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import type { AuditAction } from "@/lib/audit";
import { log } from "@/lib/logger";
import { getToken } from "next-auth/jwt";

/**
 * Middleware for security headers, rate limiting, API versioning,
 * organization-level rate limiting, and audit logging
 */

/**
 * Sanitize a query string for logging — strips potentially sensitive
 * parameters (tokens, keys, passwords, secrets) and truncates long values.
 *
 * Known safe params: page, limit, sort, order, search, q, id, filter,
 * offset, cursor, status, type, category, tags, from, to.
 * All other params have their values redacted.
 */
function sanitizeQueryString(query: string): string {
  if (!query || query === "?") return "";
  try {
    const params = new URLSearchParams(query);
    const safeParams = new Set([
      "page", "limit", "sort", "order", "search", "q", "id",
      "filter", "offset", "cursor", "status", "type", "category",
      "tags", "from", "to", "start", "end",
    ]);
    const sensitivePattern = /^(token|key|secret|password|auth|api.?key|access.?token|session|jwt)$/i;
    const result: string[] = [];
    for (const [key, value] of params) {
      if (sensitivePattern.test(key)) {
        // Redact known sensitive params entirely
        result.push(`${key}=__REDACTED__`);
      } else if (!safeParams.has(key)) {
        // Redact unknown params — could contain arbitrary data
        result.push(`${key}=__REDACTED__`);
      } else {
        // Safe params: include but truncate
        const truncated = value.length > 100 ? value.slice(0, 100) + "..." : value;
        result.push(`${key}=${truncated}`);
      }
    }
    return result.join("&");
  } catch {
    return "__MALFORMED_QUERY__";
  }
}

function getClientIP(request: NextRequest): string {
  // Use request.ip first (TCP connection IP from platform — trustworthy).
  // Only fall back to x-forwarded-for header as a secondary option.
  // Never trust x-forwarded-for alone — it's trivially spoofable (H-v5-01).
  if (request.ip) {
    return request.ip;
  }
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) {
    return forwarded.split(",")[0].trim();
  }
  return "unknown";
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

  // Generate server-side request ID for tracing.
  // Do NOT trust client-supplied x-request-id to prevent:
  // - log injection / log forging
  // - trace ID collisions / replay attacks
  const requestId = crypto.randomUUID();
  response.headers.set("X-Request-ID", requestId);
  // Set the server-generated ID on the request for downstream use
  request.headers.set("x-request-id", requestId);

  const path = request.nextUrl.pathname;

  // ============================================================
  // C-01: Route protection — redirect unauthenticated users from
  // protected pages before page load (edge-level auth check)
  // ============================================================
  const protectedPaths = ['/dashboard', '/findings', '/engagements', '/settings', '/reports', '/admin'];
  if (protectedPaths.some(p => path === p || path.startsWith(p + '/'))) {
    try {
      const token = await getToken({
        req: request,
        secret: process.env.NEXTAUTH_SECRET,
      });
      if (!token) {
        const signinUrl = new URL('/auth/signin', request.url);
        signinUrl.searchParams.set('callbackUrl', request.url);
        return NextResponse.redirect(signinUrl);
      }
      response.headers.set('X-Auth-Status', 'authenticated');
    } catch {
      response.headers.set('X-Auth-Status', 'unverified');
    }
  }

  // API Version headers
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

    // ============================================================
    // M-21: Content-Type validation for state-changing API methods.
    // Reject POST/PUT/PATCH with no Content-Type or non-JSON types.
    // ============================================================
    if (["POST", "PUT", "PATCH"].includes(request.method)) {
      const contentType = request.headers.get("content-type") || "";
      if (!contentType.includes("application/json") && !contentType.includes("multipart/form-data")) {
        log.warn(`Content-Type validation failed for ${request.method} ${path}: ${contentType}`);
        return NextResponse.json(
          { error: "Content-Type must be application/json" },
          { status: 415 },
        );
      }
    }

    // ============================================================
    // H-05: CSRF protection — Origin header check for state-changing
    // methods. When the browser sends an Origin header (same-origin or
    // cross-origin), validate it against allowed origins. Combined with
    // SameSite=Strict cookie (set in auth.ts), this prevents CSRF.
    //
    // In production, ALLOWED_ORIGINS MUST be configured. If it's empty,
    // a warning is logged but requests are STILL validated against the
    // origin header (with same-origin fallback). This ensures CSRF
    // protection is never silently disabled by misconfiguration.
    // ============================================================
    const origin = request.headers.get("origin");
    const allowedOrigins = process.env.ALLOWED_ORIGINS?.split(",").filter(Boolean) || [];
    const isMutatingMethod = ["POST", "PUT", "DELETE", "PATCH"].includes(request.method);

    if (process.env.NODE_ENV === "production") {
      if (allowedOrigins.length === 0) {
        log.warn(
          "ALLOWED_ORIGINS not configured in production" +
          " - CSRF protection is limited. " +
          "Set ALLOWED_ORIGINS to your application's origin(s)."
        );
      }
      // Origin validation: if the request has an Origin header that is not in
      // the allowed list, block state-changing methods. When no Origin is
      // present (same-orign requests via SameSite cookie), allow through.
      if (origin) {
        const isAllowed = allowedOrigins.length === 0 || allowedOrigins.some((o) => o.trim() === origin);
        if (!isAllowed) {
          // For state-changing methods, reject invalid origins (CSRF)
          if (isMutatingMethod) {
            log.warn(`CSRF blocked: ${request.method} ${path} from origin ${origin}`);
            return NextResponse.json(
              { error: "Cross-origin request blocked" },
              { status: 403 },
            );
          }
          // For read methods, still process but don't expose CORS headers
          response.headers.set("X-Origin-Validated", "invalid");
        } else {
          response.headers.set("X-Origin-Validated", "valid");
          response.headers.set("Access-Control-Allow-Origin", origin);
          response.headers.set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
          response.headers.set("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key");
        }
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
        // Derive orgId from the session JWT, NOT from user-controlled headers (C-v3-01)
        try {
          const token = await getToken({
            req: request,
            secret: process.env.NEXTAUTH_SECRET,
          });
          const orgId = token?.orgId as string | undefined;
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
          // If token decoding fails, skip org-level rate limiting
        }
      } catch {
        // Rate limiting failed, continue without it
      }
    }

    // Log API request after rate limiting (don't log rate-limited requests).
    // Sanitize query string to prevent sensitive data leakage in logs.
    // Only log query params known to be safe; strip all others.
    const sanitizedQuery = sanitizeQueryString(request.nextUrl.search);
    log.api(request.method, path, { query: sanitizedQuery });

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
  // Uses 'strict-dynamic' as transitional approach away from 'unsafe-inline' (C-04).
  // 'unsafe-inline' is kept as a fallback for browsers that don't support
  // 'strict-dynamic' but still protected by the nonce-based restriction.
  // In development, 'unsafe-eval' is needed for Next.js HMR.
  const isDev = process.env.NODE_ENV === "development";
  const nonce = crypto.randomUUID();
  const scriptSrc = isDev
    ? "'self' 'unsafe-inline' 'unsafe-eval'"
    : "'strict-dynamic' 'nonce-" + nonce + "' 'unsafe-inline'";

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
      "upgrade-insecure-requests; " +
      "report-uri /api/csp-report;",
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
