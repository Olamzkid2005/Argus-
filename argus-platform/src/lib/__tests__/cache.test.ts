/**
 * Tests for cache layer
 */

jest.mock("../redis", () => ({
  __esModule: true,
  default: {
    setex: jest.fn(() => Promise.resolve("OK")),
    get: jest.fn(() => Promise.resolve(null)),
    del: jest.fn(() => Promise.resolve(1)),
    sadd: jest.fn(() => Promise.resolve(1)),
    expire: jest.fn(() => Promise.resolve(1)),
    smembers: jest.fn(() => Promise.resolve([])),
    info: jest.fn(() => Promise.resolve("db0:keys=0,expires=0")),
  },
}));

import redis from "../redis";
import {
  setCache,
  getCache,
  deleteCache,
  invalidateByTag,
  invalidateByTags,
  getCacheStats,
} from "../cache";

describe("Cache", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe("setCache / getCache", () => {
    it("should store and retrieve a value", async () => {
      const entry = JSON.stringify({ data: { data: "value" }, tags: [], createdAt: Date.now() });
      (redis.get as jest.Mock).mockResolvedValue(entry);

      await setCache("test-key", { data: "value" });
      const result = await getCache("test-key");
      expect(result).toEqual({ data: "value" });
    });

    it("should return null for missing key", async () => {
      (redis.get as jest.Mock).mockResolvedValue(null);
      const result = await getCache("missing-key");
      expect(result).toBeNull();
    });

    it("should respect TTL", async () => {
      (redis.get as jest.Mock).mockResolvedValue(null);
      await setCache("ttl-key", "value", { ttl: 1 });
      const result = await getCache("ttl-key");
      expect(result).toBeNull();
    });
  });

  describe("invalidateByTag", () => {
    it("should invalidate entries by tag", async () => {
      (redis.smembers as jest.Mock).mockImplementation((key: string) => {
        if (key === "tag:engagement") return Promise.resolve(["eng-1"]);
        return Promise.resolve([]);
      });

      await invalidateByTag("engagement");

      expect(redis.del).toHaveBeenCalledWith("eng-1");
      expect(redis.del).toHaveBeenCalledWith("tag:engagement");
    });
  });

  describe("invalidateByTags", () => {
    it("should invalidate multiple tags", async () => {
      (redis.smembers as jest.Mock).mockImplementation((key: string) => {
        if (key === "tag:engagement") return Promise.resolve(["eng-1"]);
        if (key === "tag:finding") return Promise.resolve(["find-1"]);
        return Promise.resolve([]);
      });

      await invalidateByTags(["engagement", "finding"]);

      expect(redis.del).toHaveBeenCalledWith("eng-1");
      expect(redis.del).toHaveBeenCalledWith("find-1");
    });
  });

  describe("getCacheStats", () => {
    it("should return cache statistics", async () => {
      (redis.info as jest.Mock).mockResolvedValue("db0:keys=2,expires=0");
      const stats = await getCacheStats();
      expect(stats.status).toBe("available");
      expect(stats.keys).toBe(2);
    });
  });
});
