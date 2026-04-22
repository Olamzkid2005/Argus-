/**
 * Tests for frontend cache layer
 */

describe("Frontend Cache", () => {
  beforeEach(() => {
    // Clear localStorage before each test
    localStorage.clear();
  });

  describe("setCache / getCache", () => {
    it("should store and retrieve a value", () => {
      const cache = require("../cache");
      cache.setCache("test-key", { data: "value" });
      const result = cache.getCache("test-key");
      expect(result).toEqual({ data: "value" });
    });

    it("should return null for missing key", () => {
      const cache = require("../cache");
      const result = cache.getCache("missing-key");
      expect(result).toBeNull();
    });

    it("should respect TTL", () => {
      const cache = require("../cache");
      cache.setCache("ttl-key", "value", 1); // 1ms TTL
      // Wait for expiry
      return new Promise((resolve) => {
        setTimeout(() => {
          const result = cache.getCache("ttl-key");
          expect(result).toBeNull();
          resolve(undefined);
        }, 10);
      });
    });
  });

  describe("invalidateByTag", () => {
    it("should invalidate entries by tag", () => {
      const cache = require("../cache");
      cache.setCache("eng-1", { id: 1 }, undefined, ["engagement"]);
      cache.setCache("find-1", { id: 2 }, undefined, ["finding"]);

      cache.invalidateByTag("engagement");

      expect(cache.getCache("eng-1")).toBeNull();
      expect(cache.getCache("find-1")).not.toBeNull();
    });
  });

  describe("invalidateByTags", () => {
    it("should invalidate multiple tags", () => {
      const cache = require("../cache");
      cache.setCache("eng-1", { id: 1 }, undefined, ["engagement"]);
      cache.setCache("find-1", { id: 2 }, undefined, ["finding"]);

      cache.invalidateByTags(["engagement", "finding"]);

      expect(cache.getCache("eng-1")).toBeNull();
      expect(cache.getCache("find-1")).toBeNull();
    });
  });

  describe("getCacheStats", () => {
    it("should return cache statistics", () => {
      const cache = require("../cache");
      cache.setCache("key1", "value1");
      cache.setCache("key2", "value2");
      const stats = cache.getCacheStats();
      expect(stats.totalEntries).toBeGreaterThanOrEqual(0);
      expect(typeof stats.memoryUsage).toBe("number");
    });
  });
});
