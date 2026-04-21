/**
 * Enhanced caching layer with TTL strategies and invalidation
 *
 * Provides Redis-based caching for frequently accessed data
 * with support for cache tags, invalidation patterns, and CDN integration.
 */

import redis from "./redis";

const DEFAULT_TTL = 300; // 5 minutes

interface CacheOptions {
  ttl?: number;
  key?: string;
  tags?: string[];
}

interface CacheEntry<T> {
  data: T;
  tags: string[];
  createdAt: number;
}

/**
 * Set cache entry with optional tags for targeted invalidation
 */
export async function setCache<T>(
  key: string,
  value: T,
  options: CacheOptions = {}
): Promise<void> {
  const { ttl = DEFAULT_TTL, tags = [] } = options;

  try {
    if (!redis) return;

    const entry: CacheEntry<T> = {
      data: value,
      tags,
      createdAt: Date.now(),
    };

    await redis.setex(key, ttl, JSON.stringify(entry));

    // Add key to tag sets for invalidation
    for (const tag of tags) {
      await redis.sadd(`tag:${tag}`, key);
      await redis.expire(`tag:${tag}`, ttl * 2);
    }
  } catch {
    // Ignore cache write errors
  }
}

/**
 * Get cache entry
 */
export async function getCache<T>(key: string): Promise<T | null> {
  try {
    if (!redis) return null;

    const cached = await redis.get(key);
    if (!cached) return null;

    const entry: CacheEntry<T> = JSON.parse(cached);
    return entry.data;
  } catch {
    return null;
  }
}

/**
 * Delete cache entry
 */
export async function deleteCache(key: string): Promise<void> {
  try {
    if (!redis) return;
    await redis.del(key);
  } catch {
    // Ignore
  }
}

/**
 * Invalidate cache by tag
 */
export async function invalidateByTag(tag: string): Promise<number> {
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
 * Invalidate cache by multiple tags
 */
export async function invalidateByTags(tags: string[]): Promise<number> {
  let total = 0;
  for (const tag of tags) {
    total += await invalidateByTag(tag);
  }
  return total;
}

/**
 * Invalidate cache by pattern
 */
export async function invalidateByPattern(pattern: string): Promise<void> {
  try {
    if (!redis) return;

    const keys = await redis.keys(pattern);
    if (keys.length > 0) {
      await redis.del(...keys);
    }
  } catch {
    // Ignore
  }
}

/**
 * Cache decorator with tag-based invalidation
 */
export async function withCache<T>(
  fn: () => Promise<T>,
  key: string,
  options: CacheOptions = {}
): Promise<T> {
  const cached = await getCache<T>(key);
  if (cached !== null) {
    return cached;
  }

  const result = await fn();
  await setCache(key, result, options);
  return result;
}

/**
 * Get cache statistics
 */
export async function getCacheStats(): Promise<{
  status: string;
  keys?: number;
  memory?: string;
}> {
  try {
    if (!redis) return { status: "unavailable" };

    const info = await redis.info("keyspace");
    const lines = info.split("\r\n");
    const dbLine = lines.find((l) => l.startsWith("db0:"));

    return {
      status: "available",
      keys: dbLine ? parseInt(dbLine.split(",")[0].split("=")[1]) : 0,
      memory: "N/A",
    };
  } catch {
    return { status: "error" };
  }
}
