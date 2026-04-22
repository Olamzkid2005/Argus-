/**
 * Tests for ResilientWebSocket
 */

describe("ResilientWebSocket", () => {
  let mockWebSocket: any;

  beforeEach(() => {
    mockWebSocket = {
      send: jest.fn(),
      close: jest.fn(),
      readyState: 1, // OPEN
      onopen: null,
      onmessage: null,
      onclose: null,
      onerror: null,
    };
    global.WebSocket = jest.fn(() => mockWebSocket) as any;
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it("should connect on instantiation", () => {
    const { ResilientWebSocket } = require("../websocket");
    const ws = new ResilientWebSocket("wss://example.com/socket");
    expect(global.WebSocket).toHaveBeenCalledWith("wss://example.com/socket");
    ws.disconnect();
  });

  it("should call onMessage when message received", () => {
    const { ResilientWebSocket } = require("../websocket");
    const onMessage = jest.fn();
    const ws = new ResilientWebSocket("wss://example.com/socket", {
      onMessage,
    });

    // Simulate message
    const event = { data: JSON.stringify({ type: "test", data: {} }) };
    if (mockWebSocket.onmessage) mockWebSocket.onmessage(event);

    expect(onMessage).toHaveBeenCalled();
    ws.disconnect();
  });

  it("should reconnect on close", (done) => {
    const { ResilientWebSocket } = require("../websocket");
    const ws = new ResilientWebSocket("wss://example.com/socket", {
      reconnectInterval: 50,
      maxReconnectAttempts: 2,
    });

    // Simulate close
    setTimeout(() => {
      if (mockWebSocket.onclose) mockWebSocket.onclose({ code: 1006 });
    }, 10);

    setTimeout(() => {
      expect(global.WebSocket).toHaveBeenCalledTimes(2); // Initial + 1 reconnect
      ws.disconnect();
      done();
    }, 150);
  });

  it("should filter events by severity", () => {
    const { ResilientWebSocket } = require("../websocket");
    const onMessage = jest.fn();
    const ws = new ResilientWebSocket("wss://example.com/socket", {
      onMessage,
      severityFilter: ["CRITICAL", "HIGH"],
    });

    const criticalEvent = { data: JSON.stringify({ type: "finding", data: { severity: "CRITICAL" } }) };
    const lowEvent = { data: JSON.stringify({ type: "finding", data: { severity: "LOW" } }) };

    if (mockWebSocket.onmessage) {
      mockWebSocket.onmessage(criticalEvent);
      mockWebSocket.onmessage(lowEvent);
    }

    expect(onMessage).toHaveBeenCalledTimes(1);
    ws.disconnect();
  });

  it("should filter events by type", () => {
    const { ResilientWebSocket } = require("../websocket");
    const onMessage = jest.fn();
    const ws = new ResilientWebSocket("wss://example.com/socket", {
      onMessage,
      typeFilter: ["finding_discovered"],
    });

    const findingEvent = { data: JSON.stringify({ type: "finding_discovered", data: {} }) };
    const stateEvent = { data: JSON.stringify({ type: "state_transition", data: {} }) };

    if (mockWebSocket.onmessage) {
      mockWebSocket.onmessage(findingEvent);
      mockWebSocket.onmessage(stateEvent);
    }

    expect(onMessage).toHaveBeenCalledTimes(1);
    ws.disconnect();
  });

  it("should batch events", (done) => {
    const { ResilientWebSocket } = require("../websocket");
    const onMessage = jest.fn();
    const ws = new ResilientWebSocket("wss://example.com/socket", {
      onMessage,
      batchSize: 3,
      batchInterval: 100,
    });

    const event = { data: JSON.stringify({ type: "finding", data: { id: 1 } }) };

    if (mockWebSocket.onmessage) {
      mockWebSocket.onmessage(event);
      mockWebSocket.onmessage(event);
      mockWebSocket.onmessage(event);
    }

    setTimeout(() => {
      expect(onMessage).toHaveBeenCalledTimes(3);
      ws.disconnect();
      done();
    }, 200);
  });

  it("should track connection status", () => {
    const { ResilientWebSocket } = require("../websocket");
    const ws = new ResilientWebSocket("wss://example.com/socket");

    expect(ws.getStatus()).toBe("connecting");

    if (mockWebSocket.onopen) mockWebSocket.onopen({});
    expect(ws.getStatus()).toBe("connected");

    ws.disconnect();
    expect(ws.getStatus()).toBe("disconnected");
  });
});
