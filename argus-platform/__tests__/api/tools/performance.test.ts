/**
 * Tests for Tool Performance API Endpoint
 *
 * Requirements: 22.3, 22.4
 */
import { NextRequest } from "next/server";
import { GET } from "@/app/api/tools/performance/route";

// Mock session
jest.mock("@/lib/session", () => ({
  requireAuth: jest.fn(),
}));

import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

describe("GET /api/tools/performance", () => {
  let mockQuery: jest.Mock;
  let mockRequireAuth: jest.Mock;

  beforeEach(() => {
    mockQuery = pool.query as jest.Mock;
    mockRequireAuth = requireAuth as jest.Mock;
    jest.clearAllMocks();
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  describe("Authentication", () => {
    it("should return 401 when not authenticated", async () => {
      mockRequireAuth.mockRejectedValue(new Error("Unauthorized"));

      const req = new NextRequest("http://localhost/api/tools/performance");
      const response = await GET(req);
      const data = await response.json();

      expect(response.status).toBe(401);
      expect(data.error).toBe("Unauthorized");
    });
  });

  describe("Query Parameters", () => {
    beforeEach(() => {
      mockRequireAuth.mockResolvedValue({
        user: { id: "user-123", orgId: "org-123", role: "user" },
        expires: "2024-12-31",
      });
    });

    it("should use default 7 days when not specified", async () => {
      mockQuery.mockResolvedValueOnce({ rows: [] });

      const req = new NextRequest("http://localhost/api/tools/performance");
      const response = await GET(req);

      expect(mockQuery).toHaveBeenCalledWith(
        expect.stringContaining("INTERVAL"),
        [7],
      );
    });

    it("should accept custom days parameter", async () => {
      mockQuery.mockResolvedValueOnce({ rows: [] });

      const req = new NextRequest(
        "http://localhost/api/tools/performance?days=30",
      );
      const response = await GET(req);

      expect(mockQuery).toHaveBeenCalledWith(
        expect.stringContaining("INTERVAL"),
        [30],
      );
    });

    it("should reject invalid days parameter (negative)", async () => {
      const req = new NextRequest(
        "http://localhost/api/tools/performance?days=-1",
      );
      const response = await GET(req);
      const data = await response.json();

      expect(response.status).toBe(400);
      expect(data.error).toContain("Invalid");
    });

    it("should reject invalid days parameter (too large)", async () => {
      const req = new NextRequest(
        "http://localhost/api/tools/performance?days=500",
      );
      const response = await GET(req);
      const data = await response.json();

      expect(response.status).toBe(400);
      expect(data.error).toContain("Invalid");
    });

    it("should filter by tool name when provided", async () => {
      mockQuery.mockResolvedValueOnce({ rows: [] });

      const req = new NextRequest(
        "http://localhost/api/tools/performance?tool=nuclei",
      );
      const response = await GET(req);

      expect(mockQuery).toHaveBeenCalledWith(
        expect.stringContaining("tool_name = $1"),
        ["nuclei", 7],
      );
    });
  });

  describe("Response Format", () => {
    beforeEach(() => {
      mockRequireAuth.mockResolvedValue({
        user: { id: "user-123", orgId: "org-123", role: "user" },
        expires: "2024-12-31",
      });
    });

    it("should return tools array with performance stats", async () => {
      const mockStats = [
        {
          tool_name: "nuclei",
          total_executions: "100",
          success_count: "95",
          avg_duration_ms: "1500.50",
          success_rate: "95.00",
          min_duration_ms: 500,
          max_duration_ms: 3000,
        },
        {
          tool_name: "httpx",
          total_executions: "50",
          success_count: "48",
          avg_duration_ms: "200.00",
          success_rate: "96.00",
          min_duration_ms: 100,
          max_duration_ms: 500,
        },
      ];

      mockQuery.mockResolvedValueOnce({ rows: mockStats });

      const req = new NextRequest("http://localhost/api/tools/performance");
      const response = await GET(req);
      const data = await response.json();

      expect(response.status).toBe(200);
      expect(data.tools).toHaveLength(2);
      expect(data.tools[0].tool_name).toBe("nuclei");
      expect(data.summary).toBeDefined();
      expect(data.summary.total_tools).toBe(2);
      expect(data.summary.total_executions).toBe(150);
      expect(data.days).toBe(7);
      expect(data.generated_at).toBeDefined();
    });

    it("should return summary with calculated statistics", async () => {
      const mockStats = [
        {
          tool_name: "nuclei",
          total_executions: "100",
          success_count: "95",
          avg_duration_ms: "1500.00",
          success_rate: "95.00",
          min_duration_ms: 500,
          max_duration_ms: 3000,
        },
      ];

      mockQuery.mockResolvedValueOnce({ rows: mockStats });

      const req = new NextRequest("http://localhost/api/tools/performance");
      const response = await GET(req);
      const data = await response.json();

      expect(data.summary.total_successes).toBe(95);
      expect(data.summary.overall_success_rate).toBe(95);
      expect(data.summary.avg_duration_across_tools).toBe(1500);
    });

    it("should return empty array when no metrics exist", async () => {
      mockQuery.mockResolvedValueOnce({ rows: [] });

      const req = new NextRequest("http://localhost/api/tools/performance");
      const response = await GET(req);
      const data = await response.json();

      expect(response.status).toBe(200);
      expect(data.tools).toHaveLength(0);
      expect(data.summary.total_tools).toBe(0);
      expect(data.summary.total_executions).toBe(0);
    });

    it("should return message when specific tool has no metrics", async () => {
      mockQuery.mockResolvedValueOnce({ rows: [] });

      const req = new NextRequest(
        "http://localhost/api/tools/performance?tool=unknown",
      );
      const response = await GET(req);
      const data = await response.json();

      expect(response.status).toBe(200);
      expect(data.tool).toBe("unknown");
      expect(data.message).toContain("No metrics found");
      expect(data.stats).toBeNull();
    });
  });

  describe("Error Handling", () => {
    it("should handle database errors gracefully", async () => {
      mockRequireAuth.mockResolvedValue({
        user: { id: "user-123", orgId: "org-123", role: "user" },
        expires: "2024-12-31",
      });
      mockQuery.mockRejectedValue(new Error("Database connection failed"));

      const req = new NextRequest("http://localhost/api/tools/performance");
      const response = await GET(req);
      const data = await response.json();

      expect(response.status).toBe(500);
      expect(data.error).toContain("Failed to fetch");
    });
  });
});
