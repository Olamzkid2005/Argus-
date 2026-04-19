/**
 * Tests for POST /api/engagement/[id]/approve endpoint
 *
 * Requirements: 33.2, 33.3, 33.4
 */

// Mock dependencies
jest.mock("@/lib/session", () => ({
  requireAuth: jest.fn(),
}));

jest.mock("@/lib/authorization", () => ({
  requireEngagementAccess: jest.fn(),
}));

jest.mock("@/lib/redis", () => ({
  pushJob: jest.fn(),
}));

jest.mock("pg", () => {
  const mockClient = {
    query: jest.fn(),
    release: jest.fn(),
  };

  const mockPool = {
    connect: jest.fn(() => Promise.resolve(mockClient)),
  };

  return {
    Pool: jest.fn(() => mockPool),
  };
});

import { POST } from "@/app/api/engagement/[id]/approve/route";
import { requireAuth } from "@/lib/session";
import { requireEngagementAccess } from "@/lib/authorization";
import { pushJob } from "@/lib/redis";
import { Pool } from "pg";

describe("POST /api/engagement/[id]/approve", () => {
  let mockPool: any;
  let mockClient: any;

  beforeEach(() => {
    jest.clearAllMocks();

    // Setup mock pool and client
    mockPool = new Pool();
    mockClient = {
      query: jest.fn(),
      release: jest.fn(),
    };
    (mockPool.connect as jest.Mock).mockResolvedValue(mockClient);

    // Setup default auth mock
    (requireAuth as jest.Mock).mockResolvedValue({
      user: {
        id: "user-123",
        orgId: "org-123",
        email: "test@example.com",
        role: "user",
      },
    });

    (requireEngagementAccess as jest.Mock).mockResolvedValue(undefined);
  });

  it("should approve engagement and push scan job to queue", async () => {
    const engagementId = "engagement-123";

    // Mock engagement query result
    mockClient.query
      .mockResolvedValueOnce({ rows: [] }) // BEGIN
      .mockResolvedValueOnce({
        // SELECT engagement
        rows: [
          {
            id: engagementId,
            status: "awaiting_approval",
            target_url: "https://example.com",
            max_cycles: 5,
            max_depth: 3,
            max_cost: 0.5,
          },
        ],
      })
      .mockResolvedValueOnce({ rows: [] }) // UPDATE engagement
      .mockResolvedValueOnce({ rows: [] }) // INSERT state transition
      .mockResolvedValueOnce({ rows: [] }); // COMMIT

    const request = new Request(
      "http://localhost:3000/api/engagement/engagement-123/approve",
      {
        method: "POST",
      },
    );

    const params = Promise.resolve({ id: engagementId });
    const response = await POST(request, { params });

    expect(response.status).toBe(200);

    const data = await response.json();
    expect(data.message).toBe("Engagement approved and scan job queued");
    expect(data.engagement_id).toBe(engagementId);
    expect(data.status).toBe("scanning");
    expect(data.trace_id).toBeDefined();

    // Verify state transition was recorded
    expect(mockClient.query).toHaveBeenCalledWith(
      expect.stringContaining("UPDATE engagements SET status"),
      ["scanning", engagementId],
    );

    expect(mockClient.query).toHaveBeenCalledWith(
      expect.stringContaining("INSERT INTO engagement_states"),
      expect.arrayContaining([
        expect.any(String), // id
        engagementId,
        "awaiting_approval",
        "scanning",
        "User approved findings",
      ]),
    );

    // Verify scan job was pushed to queue
    expect(pushJob).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "scan",
        engagement_id: engagementId,
        target: "https://example.com",
        budget: {
          max_cycles: 5,
          max_depth: 3,
          max_cost: 0.5,
        },
      }),
    );
  });

  it("should return 404 if engagement not found", async () => {
    const engagementId = "nonexistent-123";

    mockClient.query
      .mockResolvedValueOnce({ rows: [] }) // BEGIN
      .mockResolvedValueOnce({ rows: [] }) // SELECT engagement (empty)
      .mockResolvedValueOnce({ rows: [] }); // ROLLBACK

    const request = new Request(
      "http://localhost:3000/api/engagement/nonexistent-123/approve",
      {
        method: "POST",
      },
    );

    const params = Promise.resolve({ id: engagementId });
    const response = await POST(request, { params });

    expect(response.status).toBe(404);

    const data = await response.json();
    expect(data.error).toBe("Engagement not found");

    // Verify transaction was rolled back
    expect(mockClient.query).toHaveBeenCalledWith("ROLLBACK");
  });

  it("should return 400 if engagement is not in awaiting_approval state", async () => {
    const engagementId = "engagement-123";

    mockClient.query
      .mockResolvedValueOnce({ rows: [] }) // BEGIN
      .mockResolvedValueOnce({
        // SELECT engagement
        rows: [
          {
            id: engagementId,
            status: "scanning", // Wrong state
            target_url: "https://example.com",
          },
        ],
      })
      .mockResolvedValueOnce({ rows: [] }); // ROLLBACK

    const request = new Request(
      "http://localhost:3000/api/engagement/engagement-123/approve",
      {
        method: "POST",
      },
    );

    const params = Promise.resolve({ id: engagementId });
    const response = await POST(request, { params });

    expect(response.status).toBe(400);

    const data = await response.json();
    expect(data.error).toContain("Cannot approve engagement in scanning state");
    expect(data.error).toContain("Must be in awaiting_approval state");

    // Verify transaction was rolled back
    expect(mockClient.query).toHaveBeenCalledWith("ROLLBACK");
  });

  it("should return 401 if user is not authenticated", async () => {
    (requireAuth as jest.Mock).mockRejectedValue(new Error("Unauthorized"));

    const request = new Request(
      "http://localhost:3000/api/engagement/engagement-123/approve",
      {
        method: "POST",
      },
    );

    const params = Promise.resolve({ id: "engagement-123" });
    const response = await POST(request, { params });

    expect(response.status).toBe(401);

    const data = await response.json();
    expect(data.error).toBe("Unauthorized");
  });

  it("should return 403 if user does not have access to engagement", async () => {
    (requireEngagementAccess as jest.Mock).mockRejectedValue(
      new Error("Forbidden: Access denied"),
    );

    const request = new Request(
      "http://localhost:3000/api/engagement/engagement-123/approve",
      {
        method: "POST",
      },
    );

    const params = Promise.resolve({ id: "engagement-123" });
    const response = await POST(request, { params });

    expect(response.status).toBe(403);

    const data = await response.json();
    expect(data.error).toBe("Forbidden: Access denied");
  });

  it("should rollback transaction on database error", async () => {
    const engagementId = "engagement-123";

    mockClient.query
      .mockResolvedValueOnce({ rows: [] }) // BEGIN
      .mockResolvedValueOnce({
        // SELECT engagement
        rows: [
          {
            id: engagementId,
            status: "awaiting_approval",
            target_url: "https://example.com",
            max_cycles: 5,
            max_depth: 3,
            max_cost: 0.5,
          },
        ],
      })
      .mockRejectedValueOnce(new Error("Database error")); // UPDATE fails

    const request = new Request(
      "http://localhost:3000/api/engagement/engagement-123/approve",
      {
        method: "POST",
      },
    );

    const params = Promise.resolve({ id: engagementId });
    const response = await POST(request, { params });

    expect(response.status).toBe(500);

    const data = await response.json();
    expect(data.error).toBe("Failed to approve engagement");

    // Verify transaction was rolled back
    expect(mockClient.query).toHaveBeenCalledWith("ROLLBACK");
  });
});
