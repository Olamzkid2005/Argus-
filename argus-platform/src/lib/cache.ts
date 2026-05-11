/**
 * Simple in-memory cache with TTL for API route responses.
 * Uses Redis if available, falls back to Map.
 */

import redis from "@/lib/redis";

interface CacheEntry<T> {
  data: T;
  expiresAt: number;
}

interface CacheOptions {
  ttlSeconds: number;
  keyGenerator?: (...args: any[]) => string;
}

const memoryCache = new Map<string, CacheEntry<any>>();
const MEMORY_CACHE_MAX_SIZE = 10_000;

function evictMemoryCacheIfNeeded(): void {
  if (memoryCache.size <= MEMORY_CACHE_MAX_SIZE) return;
  // LRU: delete oldest entries (insertion order in Map)
  const excess = memoryCache.size - MEMORY_CACHE_MAX_SIZE;
  let deleted = 0;
  for (const key of memoryCache.keys()) {
    memoryCache.delete(key);
    deleted++;
    if (deleted >= excess) break;
  }
}

/**
 * Check if Redis is connected and available.
 * Result is cached for 5 seconds to avoid pinging Redis on every call.
 */
let _redisAvailable: boolean | null = null;
let _redisAvailableAt = 0;
const REDIS_AVAILABLE_TTL = 5_000; // 5 seconds

async function isRedisAvailable(): Promise<boolean> {
  if (_redisAvailable !== null && Date.now() - _redisAvailableAt < REDIS_AVAILABLE_TTL) {
    return _redisAvailable;
  }
  try {
    await redis.ping();
    _redisAvailable = true;
  } catch {
    _redisAvailable = false;
  }
  _redisAvailableAt = Date.now();
  return _redisAvailable;
}

/**
 * Get a value from the cache (Redis or in-memory fallback).
 */
async function getCache<T>(key: string): Promise<T | null> {
  try {
    if (await isRedisAvailable()) {
      const value = await redis.get(key);
      if (value) {
        return JSON.parse(value) as T;
      }
    }
  } catch {
    // Redis error — fall through to in-memory
  }

  const entry = memoryCache.get(key);
  if (entry && entry.expiresAt > Date.now()) {
    return entry.data;
  }

  // Expired or missing — clean up
  memoryCache.delete(key);
  return null;
}

/**
 * Set a value in the cache (Redis or in-memory fallback).
 */
async function setCache<T>(key: string, value: T, ttlSeconds: number): Promise<void> {
  try {
    if (await isRedisAvailable()) {
      await redis.setex(key, ttlSeconds, JSON.stringify(value));
      return;
    }
  } catch {
    // Redis error — fall through to in-memory
  }

  evictMemoryCacheIfNeeded();
  memoryCache.set(key, {
    data: value,
    expiresAt: Date.now() + ttlSeconds * 1000,
  });
}

/**
 * Method decorator that caches the result of an async function.
 *
 * Uses Redis when available, otherwise falls back to an in-memory Map.
 * Stale entries are evicted lazily on access.
 *
 * @example
 * class MyService {
 *   @withCache({ ttlSeconds: 60, keyGenerator: (id) => `user:${id}` })
 *   async getUser(id: string) {
 *     return db.user.findById(id);
 *   }
 * }
 */
export function withCache<T>(options: CacheOptions) {
  return function (
    target: any,
    propertyKey: string,
    descriptor: PropertyDescriptor
  ) {
    const original = descriptor.value;

    descriptor.value = async function (...args: any[]) {
      const key = options.keyGenerator
        ? options.keyGenerator(...args)
        : `${propertyKey}:${JSON.stringify(args)}`;

      const cached = await getCache<T>(key);
      if (cached !== null) {
        return cached;
      }

      const result = await original.apply(this, args);
      await setCache(key, result, options.ttlSeconds);

      return result;
    };
  };
}

/**
 * Execute a fetcher and cache its result.
 *
 * If the key exists in the cache and hasn't expired, the cached value
 * is returned immediately. Otherwise the fetcher is executed and the
 * result is stored for the given TTL.
 *
 * @param key        Cache key
 * @param fetcher    Function that produces the value to cache
 * @param ttlSeconds Time-to-live in seconds (default: 60)
 *
 * @example
 * const data = await cacheResponse(
 *   `dashboard:stats:${engagementId}`,
 *   () => fetchDashboardStats(engagementId),
 *   120
 * );
 */
export async function cacheResponse<T>(
  key: string,
  fetcher: () => Promise<T>,
  ttlSeconds: number = 60
): Promise<T> {
  const cached = await getCache<T>(key);
  if (cached !== null) {
    return cached;
  }

  const result = await fetcher();
  await setCache(key, result, ttlSeconds);
  return result;
}

/**
 * Wrap a Next.js API route handler with response caching.
 *
 * The wrapped handler will return a cached Response when available,
 * otherwise it runs the handler and caches the JSON response.
 *
 * @param handler  Original route handler: (req: Request) => Promise<Response>
 * @param options  Cache options
 *
 * @example
 * export const GET = cachedRouteHandler(
 *   async (req: Request) => {
 *     const data = await expensiveQuery();
 *     return Response.json(data);
 *   },
 *   {
 *     ttlSeconds: 300,
 *     keyFromRequest: (req) => `api:reports:${req.url}`,
 *   }
 * );
 */
export function cachedRouteHandler<T>(
  handler: (req: Request) => Promise<Response>,
  options: { ttlSeconds: number; keyFromRequest?: (req: Request) => string }
) {
  return async function (req: Request): Promise<Response> {
    const cacheKey = options.keyFromRequest
      ? options.keyFromRequest(req)
      : `route:${req.method}:${req.url}`;

    const cached = await getCache<{ body: string; status: number; headers: Record<string, string> }>(cacheKey);
    if (cached !== null) {
      return new Response(cached.body, {
        status: cached.status,
        headers: cached.headers,
      });
    }

    const response = await handler(req);

    // Only cache successful JSON responses
    const contentType = response.headers.get("content-type") || "";
    if (response.ok && contentType.includes("application/json")) {
      const body = await response.text();
      const headers: Record<string, string> = {};
      response.headers.forEach((value, key) => {
        headers[key] = value;
      });

      await setCache(cacheKey, { body, status: response.status, headers }, options.ttlSeconds);

      return new Response(body, {
        status: response.status,
        headers,
      });
    }

    return response;
  };
}
