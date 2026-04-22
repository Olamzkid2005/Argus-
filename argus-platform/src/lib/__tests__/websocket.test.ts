/**
 * Tests for ResilientWebSocket (HTTP polling implementation)
 */

import { ResilientWebSocket } from "../websocket";

const flushPromises = async () => {
  for (let i = 0; i < 10; i++) {
    await Promise.resolve();
  }
};

describe("ResilientWebSocket", () => {
  beforeEach(() => {
    jest.useFakeTimers({ doNotFake: ["nextTick"] });
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.useRealTimers();
    jest.clearAllMocks();
  });

  it("should initialize with disconnected status", () => {
    const ws = new ResilientWebSocket({ engagementId: "eng-123" });
    expect(ws.connectionStatus).toBe("disconnected");
  });

  it("should call onEvent when poll returns events", async () => {
    const onEvent = jest.fn();
    const ws = new ResilientWebSocket({
      engagementId: "eng-123",
      onEvent,
      pollInterval: 2000,
    });

    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        events: [
          { type: "finding_discovered", timestamp: new Date().toISOString(), data: { severity: "HIGH" } },
        ],
      }),
    });

    ws.connect();
    await flushPromises();

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/ws/engagement/eng-123/poll"),
      expect.any(Object)
    );
    expect(onEvent).toHaveBeenCalledTimes(1);
    ws.disconnect();
  });

  it("should update connection status on connect", () => {
    const onStatusChange = jest.fn();
    const ws = new ResilientWebSocket({
      engagementId: "eng-123",
      onStatusChange,
    });

    ws.connect();
    expect(ws.connectionStatus).toBe("connecting");
    expect(onStatusChange).toHaveBeenCalledWith("connecting");
    ws.disconnect();
  });

  it("should disconnect and set status to disconnected", () => {
    const onStatusChange = jest.fn();
    const ws = new ResilientWebSocket({
      engagementId: "eng-123",
      onStatusChange,
    });

    ws.connect();
    ws.disconnect();
    expect(ws.connectionStatus).toBe("disconnected");
    expect(onStatusChange).toHaveBeenCalledWith("disconnected");
  });

  it("should filter events by severity", async () => {
    const onEvent = jest.fn();
    const ws = new ResilientWebSocket({
      engagementId: "eng-123",
      onEvent,
      minSeverity: "HIGH",
      pollInterval: 2000,
    });

    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        events: [
          { type: "finding", timestamp: new Date().toISOString(), data: { severity: "CRITICAL" } },
          { type: "finding", timestamp: new Date().toISOString(), data: { severity: "LOW" } },
          { type: "finding", timestamp: new Date().toISOString(), data: { severity: "HIGH" } },
        ],
      }),
    });

    ws.connect();
    await flushPromises();

    expect(onEvent).toHaveBeenCalledTimes(2);
    ws.disconnect();
  });

  it("should filter events by type", async () => {
    const onEvent = jest.fn();
    const ws = new ResilientWebSocket({
      engagementId: "eng-123",
      onEvent,
      eventTypes: ["finding_discovered"],
      pollInterval: 2000,
    });

    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        events: [
          { type: "finding_discovered", timestamp: new Date().toISOString(), data: {} },
          { type: "state_transition", timestamp: new Date().toISOString(), data: {} },
        ],
      }),
    });

    ws.connect();
    await flushPromises();

    expect(onEvent).toHaveBeenCalledTimes(1);
    ws.disconnect();
  });

  it("should batch events from a single poll", async () => {
    const onEvent = jest.fn();
    const ws = new ResilientWebSocket({
      engagementId: "eng-123",
      onEvent,
      batchSize: 5,
      pollInterval: 2000,
    });

    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        events: [
          { type: "finding", timestamp: new Date().toISOString(), data: { id: 1 } },
          { type: "finding", timestamp: new Date().toISOString(), data: { id: 2 } },
          { type: "finding", timestamp: new Date().toISOString(), data: { id: 3 } },
        ],
      }),
    });

    ws.connect();
    await flushPromises();

    expect(onEvent).toHaveBeenCalledTimes(3);
    ws.disconnect();
  });

  it("should attempt reconnection on poll failure", async () => {
    jest.spyOn(Math, "random").mockReturnValue(0);
    const onStatusChange = jest.fn();
    const ws = new ResilientWebSocket({
      engagementId: "eng-123",
      onStatusChange,
      maxReconnectAttempts: 2,
      pollInterval: 2000,
    });

    (global.fetch as jest.Mock).mockRejectedValue(new Error("Network error"));

    ws.connect();
    await flushPromises();

    expect(ws.connectionStatus).toBe("reconnecting");

    // Fast-forward past first reconnection delay (1000ms)
    jest.advanceTimersByTime(1000);
    await flushPromises();

    expect(global.fetch).toHaveBeenCalledTimes(2);
    ws.disconnect();
    (Math.random as jest.Mock).mockRestore();
  });

  it("should stop polling when disconnected", async () => {
    const ws = new ResilientWebSocket({
      engagementId: "eng-123",
      pollInterval: 2000,
    });

    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ events: [] }),
    });

    ws.connect();
    await flushPromises();
    expect(global.fetch).toHaveBeenCalledTimes(1);

    ws.disconnect();
    jest.advanceTimersByTime(10000);
    await flushPromises();

    // Should not have called fetch again after disconnect
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });
});
