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
    // Prevent process crash on Redis connection errors (H-v4-02)
    redisClient.on("error", (err) => {
      console.error("Rate limiter Redis error:", err);
    });
    // L-18: Reset the singleton on close so the next getRedisClient() call recreates it.
    // Without this, a transient Redis failure permanently degrades rate limiting to
    // the in-memory fallback until process restart.
    redisClient.on("close", () => {
      redisClient = null;
    });
  }
  return redisClient;
}

export function createRateLimit(config: RateLimitConfig = defaultConfig) {
  return async function rateLimit(
    req: NextRequest,
  ): Promise<NextResponse | null> {
    // Use request.ip (server-recognized address) first — x-forwarded-for can be
    // spoofed by attackers to bypass rate limits (H-v5-01).
    const ip =
      req.ip ||
      req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
      "unknown";

    const key = `${ip}:${config.windowMs}:${config.maxRequests}`;
    const now = Date.now();
    const windowStart = Math.floor(now / config.windowMs) * config.windowMs;

    try {
      const redis = getRedisClient();

      // Redis-backed sliding window using atomic SET NX EX (M-19)
      // Key format: ratelimit:{ip}:{window_start}
      const windowKey = `${key}:${windowStart}`;
      // M-19: Use SET NX EX for atomic initialization to prevent the race condition
      // where INCR creates the key but EXPIRE hasn't been called yet, allowing a
      // concurrent request to also see count === 1 and skip the EXPIRE.
      const setResult = await redis.set(windowKey, 1, "PX", config.windowMs + 1000, "NX");
      const count = setResult === "OK" ? 1 : await redis.incr(windowKey);

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

// M-23: Periodic cleanup of expired in-memory rate limit entries to prevent
// unbounded memory growth under sustained traffic. Runs every 60 seconds.
const CLEANUP_INTERVAL_MS = 60000;
let cleanupTimer: ReturnType<typeof setInterval> | null = null;
function startCleanupIfNeeded() {
  if (cleanupTimer) return;
  cleanupTimer = setInterval(() => {
    const now = Date.now();
    for (const [key, record] of memoryLimits) {
      if (now > record.resetTime) {
        memoryLimits.delete(key);
      }
    }
    // Clear the timer if the map is empty to avoid unnecessary cycles
    if (memoryLimits.size === 0 && cleanupTimer) {
      clearInterval(cleanupTimer);
      cleanupTimer = null;
    }
  }, CLEANUP_INTERVAL_MS);
  // Allow the timer to not block process exit
  if (cleanupTimer && typeof cleanupTimer === "object" && "unref" in cleanupTimer) {
    cleanupTimer.unref();
  }
}

function fallbackRateLimit(
  req: NextRequest,
  config: RateLimitConfig,
): NextResponse | null {
  const ip =
    req.ip ||
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    "unknown";
  const key = `fallback:${ip}`;
  const now = Date.now();

  let record = memoryLimits.get(key);
  if (!record || now > record.resetTime) {
    record = { count: 0, resetTime: now + config.windowMs };
    startCleanupIfNeeded(); // M-23: Start periodic cleanup when first entry is created
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
