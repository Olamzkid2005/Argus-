// Rate limiter utility for API routes
import { NextRequest, NextResponse } from "next/server";
import Redis from "ioredis";

// In-memory rate limiter for simplicity (use Redis in production)
const rateLimits = new Map<string, { count: number; resetTime: number }>();

interface RateLimitConfig {
  windowMs: number; // time window in milliseconds
  maxRequests: number; // max requests per window
}

const defaultConfig: RateLimitConfig = {
  windowMs: 60000, // 1 minute
  maxRequests: 100, // 100 requests per minute
};

export function createRateLimit(config: RateLimitConfig = defaultConfig) {
  return async function rateLimit(
    req: NextRequest,
  ): Promise<NextResponse | null> {
    // Get client IP
    const ip =
      req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
      req.ip ||
      "unknown";

    const key = `ratelimit:${ip}`;
    const now = Date.now();

    // Get existing rate limit record
    let record = rateLimits.get(key);

    // Reset if window expired
    if (!record || now > record.resetTime) {
      record = {
        count: 0,
        resetTime: now + config.windowMs,
      };
    }

    // Increment count
    record.count++;
    rateLimits.set(key, record);

    // Check if exceeded
    if (record.count > config.maxRequests) {
      return NextResponse.json(
        {
          error: "Too many requests",
          retryAfter: Math.ceil((record.resetTime - now) / 1000),
        },
        {
          status: 429,
          headers: {
            "Retry-After": String(Math.ceil((record.resetTime - now) / 1000)),
            "X-RateLimit-Limit": String(config.maxRequests),
            "X-RateLimit-Remaining": "0",
          },
        },
      );
    }

    // Return rate limit headers for successful requests
    return NextResponse.json(
      { success: true },
      {
        headers: {
          "X-RateLimit-Limit": String(config.maxRequests),
          "X-RateLimit-Remaining": String(config.maxRequests - record.count),
        },
      },
    );
  };
}

// Pre-configured rate limiters
export const strictRateLimit = createRateLimit({
  windowMs: 60000,
  maxRequests: 20,
});
export const moderateRateLimit = createRateLimit({
  windowMs: 60000,
  maxRequests: 50,
});
export const lenientRateLimit = createRateLimit({
  windowMs: 60000,
  maxRequests: 100,
});
