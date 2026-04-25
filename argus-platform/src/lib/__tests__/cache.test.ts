/**
 * Tests for cache layer
 */

jest.mock("../redis", () => ({
  __esModule: true,
  default: {
    ping: jest.fn(() => Promise.resolve("PONG")),
    setex: jest.fn(() => Promise.resolve("OK")),
    get: jest.fn(() => Promise.resolve(null)),
  },
}));

import redis from "../redis";
import { withCache, cacheResponse, cachedRouteHandler } from "../cache";

describe("Cache", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe("cacheResponse", () => {
    it("should execute fetcher on cache miss and store result", async () => {
      (redis.ping as jest.Mock).mockResolvedValue("PONG");
      const fetcher = jest.fn().mockResolvedValue({ data: "value" });

      const result = await cacheResponse("test-key", fetcher, 60);

      expect(result).toEqual({ data: "value" });
      expect(fetcher).toHaveBeenCalledTimes(1);
      expect(redis.setex).toHaveBeenCalledWith(
        "test-key",
        60,
        JSON.stringify({ data: "value" })
      );
    });

    it("should return cached value without calling fetcher on cache hit", async () => {
      (redis.ping as jest.Mock).mockResolvedValue("PONG");
      (redis.get as jest.Mock).mockResolvedValue(
        JSON.stringify({ data: "cached" })
      );

      const fetcher = jest.fn();

      const result = await cacheResponse("cache-hit-key", fetcher, 60);

      expect(result).toEqual({ data: "cached" });
      expect(fetcher).not.toHaveBeenCalled();
    });

    it("should return null when fetcher returns null for missing key", async () => {
      (redis.ping as jest.Mock).mockResolvedValue("PONG");
      (redis.get as jest.Mock).mockResolvedValue(null);

      const result = await cacheResponse("missing-key", () =>
        Promise.resolve(null),
        60,
      );

      expect(result).toBeNull();
    });
  });

  describe("withCache", () => {
    it("should be a function (decorator factory)", () => {
      expect(typeof withCache).toBe("function");
    });
  });

  describe("cachedRouteHandler", () => {
    it("should be a function", () => {
      expect(typeof cachedRouteHandler).toBe("function");
    });

    it("should return a wrapped handler function", () => {
      const handler = jest.fn();
      const wrapped = cachedRouteHandler(handler, { ttlSeconds: 60 });
      expect(typeof wrapped).toBe("function");
    });
  });
});
