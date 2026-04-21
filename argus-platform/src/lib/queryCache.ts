/**
 * Query result caching using Redis for expensive database queries
 * Enhanced with tag-based invalidation and TTL strategies
 */
import redis from "./redis";

const DEFAULT_TTL = 60; // 1 minute default cache TTL

interface CacheOptions {
  ttl?: number;
  key?: string;
  tags?: string[];
  invalidateOnWrite?: boolean;
}

/**
 * Cache decorator for database queries
 * Returns cached result if available, otherwise executes query and caches result
 */
export async function withQueryCache<T>(
  queryFn: () => Promise<T>,
  cacheKey: string,
  options: CacheOptions = {}
): Promise<T> {
  const { ttl = DEFAULT_TTL, tags = [] } = options;

  // Try to get from cache first
  try {
    if (redis) {
      const cached = await redis.get(cacheKey);
      if (cached) {
        return JSON.parse(cached) as T;
      }
    }
  } catch {
    // Cache miss or error, continue to query
  }

  // Execute the query
  const result = await queryFn();

  // Cache the result with tags
  try {
    if (redis) {
      await redis.setex(cacheKey, ttl, JSON.stringify(result));

      // Add to tag sets
      for (const tag of tags) {
        await redis.sadd(`tag:${tag}`, cacheKey);
        await redis.expire(`tag:${tag}`, ttl * 2);
      }
    }
  } catch {
    // Cache write error, continue without caching
  }

  return result;
}

/**
 * Invalidate cache for a specific key pattern
 */
export async function invalidateCache(pattern: string): Promise<void> {
  try {
    if (redis) {
      const keys = await redis.keys(pattern);
      if (keys.length > 0) {
        await redis.del(...keys);
      }
    }
  } catch {
    // Ignore cache invalidation errors
  }
}

/**
 * Invalidate cache by tag
 */
export async function invalidateCacheByTag(tag: string): Promise<number> {
  try {
    if (!redis) return 0;

    const keys = await redis.smembers(`tag:${tag}`);
    if (keys.length === 0) return 0;

    await redis.del(...keys);
    await redis.del(`tag:${tag}`);

    return keys.length;
  } catch {
    return 0;
  }
}

/**
 * Invalidate all caches for engagement-related queries
 */
export async function invalidateEngagementCache(engagementId: string): Promise<void> {
  await invalidateCache(`*:engagement:${engagementId}*`);
  await invalidateCache(`*:findings:*`);
  await invalidateCacheByTag("engagements");
  await invalidateCacheByTag("findings");
}