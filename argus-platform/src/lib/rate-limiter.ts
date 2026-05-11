// Rate limiter utility for API routes — Redis-backed (horizontally scalable)
import { NextRequest, NextResponse } from "next/server";
import Redis from "ioredis";

interface RateLimitConfig {
  windowMs: number; // time window in milliseconds
  maxRequests: number; // max requests per window
}

const defaultConfig: RateLimitConfig = {
  windowMs: 60000, // 1 minute
  maxRequests: 100, // 100 requests per minute
};

// Singleton Redis client for rate limiting (reused across instances)
let redisClient: Redis | null = null;

function getRedisClient(): Redis {
  if (!redisClient) {
    redisClient = new Redis(process.env.REDIS_URL || "redis://localhost:6379", {
      keyPrefix: "ratelimit:",
      enableOfflineQueue: false,
      lazyConnect: true,
    });
  }
  return redisClient;
}

export function createRateLimit(config: RateLimitConfig = defaultConfig) {
  return async function rateLimit(
    req: NextRequest,
  ): Promise<NextResponse | null> {
    const ip =
      req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
      req.ip ||
      "unknown";

    const key = `${ip}:${config.windowMs}:${config.maxRequests}`;
    const now = Date.now();
    const windowStart = Math.floor(now / config.windowMs) * config.windowMs;

    try {
      const redis = getRedisClient();

      // Redis-backed sliding window using INCR + EXPIRE
      // Key format: ratelimit:{ip}:{window_start}
      const windowKey = `${key}:${windowStart}`;
      const count = await redis.incr(windowKey);

      if (count === 1) {
        // First request in this window — set TTL to slightly more than window
        await redis.pexpire(windowKey, config.windowMs + 1000);
      }

      // Get remaining TTL for Retry-After header
      const ttl = await redis.pttl(windowKey);
      const remaining = Math.max(0, config.maxRequests - count);

      // If exceeded, check if window has rolled over
      if (count > config.maxRequests) {
        return NextResponse.json(
          {
            error: "Too many requests",
            retryAfter: Math.ceil(Math.max(ttl, 0) / 1000),
          },
          {
            status: 429,
            headers: {
              "Retry-After": String(Math.ceil(Math.max(ttl, 0) / 1000)),
              "X-RateLimit-Limit": String(config.maxRequests),
              "X-RateLimit-Remaining": "0",
            },
          },
        );
      }

      // Add rate limit headers to the response (handled by caller via headers param)
      // Return null for successful requests
      return null;
    } catch {
      // Redis unavailable — fall back to per-instance in-memory limiter
      return fallbackRateLimit(req, config);
    }
  };
}

// Fallback in-memory rate limiter (per-instance, used when Redis is unavailable)
const memoryLimits = new Map<string, { count: number; resetTime: number }>();

function fallbackRateLimit(
  req: NextRequest,
  config: RateLimitConfig,
): NextResponse | null {
  const ip =
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    req.ip ||
    "unknown";
  const key = `fallback:${ip}`;
  const now = Date.now();

  let record = memoryLimits.get(key);
  if (!record || now > record.resetTime) {
    record = { count: 0, resetTime: now + config.windowMs };
  }

  record.count++;
  memoryLimits.set(key, record);

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

  return null;
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
