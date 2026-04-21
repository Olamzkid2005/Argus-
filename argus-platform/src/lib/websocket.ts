/**
 * WebSocket Client with Reconnection and Event Filtering
 *
 * Provides resilient WebSocket-like communication using polling
 * with exponential backoff reconnection logic.
 *
 * Features:
 * - Automatic reconnection with exponential backoff
 * - Event batching for reduced overhead
 * - Event filtering by severity/type
 * - Connection status tracking
 */

import { WebSocketEvent, WebSocketEventType } from "./websocket-events";

export type ConnectionStatus = "connecting" | "connected" | "disconnected" | "reconnecting";

interface WebSocketOptions {
  engagementId: string;
  onEvent?: (event: WebSocketEvent) => void;
  onStatusChange?: (status: ConnectionStatus) => void;
  minSeverity?: "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  eventTypes?: WebSocketEventType[];
  pollInterval?: number;
  maxReconnectAttempts?: number;
  batchSize?: number;
}

export class ResilientWebSocket {
  private engagementId: string;
  private onEvent?: (event: WebSocketEvent) => void;
  private onStatusChange?: (status: ConnectionStatus) => void;
  private minSeverity?: string;
  private eventTypes?: Set<string>;
  private pollInterval: number;
  private maxReconnectAttempts: number;
  private batchSize: number;

  private status: ConnectionStatus = "disconnected";
  private reconnectAttempts = 0;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private lastEventTime: string | null = null;
  private abortController: AbortController | null = null;
  private eventBuffer: WebSocketEvent[] = [];

  constructor(options: WebSocketOptions) {
    this.engagementId = options.engagementId;
    this.onEvent = options.onEvent;
    this.onStatusChange = options.onStatusChange;
    this.minSeverity = options.minSeverity;
    this.eventTypes = options.eventTypes ? new Set(options.eventTypes) : undefined;
    this.pollInterval = options.pollInterval || 2000;
    this.maxReconnectAttempts = options.maxReconnectAttempts || 10;
    this.batchSize = options.batchSize || 10;
  }

  get connectionStatus(): ConnectionStatus {
    return this.status;
  }

  private setStatus(status: ConnectionStatus): void {
    if (this.status !== status) {
      this.status = status;
      this.onStatusChange?.(status);
    }
  }

  connect(): void {
    if (this.status === "connected" || this.status === "connecting") return;

    this.setStatus("connecting");
    this.reconnectAttempts = 0;
    this.startPolling();
  }

  disconnect(): void {
    this.stopPolling();
    this.clearReconnectTimer();
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }
    this.setStatus("disconnected");
    this.flushBuffer();
  }

  private startPolling(): void {
    this.stopPolling();
    this.abortController = new AbortController();

    // Immediate first poll
    this.poll();

    // Set up interval
    this.pollTimer = setInterval(() => this.poll(), this.pollInterval);
  }

  private stopPolling(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  private async poll(): Promise<void> {
    if (this.status === "disconnected") return;

    try {
      const url = new URL(
        `/api/ws/engagement/${this.engagementId}/poll`,
        window.location.origin
      );
      if (this.lastEventTime) {
        url.searchParams.set("since", this.lastEventTime);
      }
      url.searchParams.set("limit", this.batchSize.toString());

      const response = await fetch(url.toString(), {
        signal: this.abortController?.signal,
      });

      if (!response.ok) {
        throw new Error(`Poll failed: ${response.status}`);
      }

      const data = await response.json();

      if (this.status !== "connected") {
        this.setStatus("connected");
        this.reconnectAttempts = 0;
      }

      if (data.events && Array.isArray(data.events)) {
        for (const event of data.events) {
          if (this.shouldProcessEvent(event)) {
            this.eventBuffer.push(event);
          }
        }
        this.flushBuffer();

        // Update last event time
        if (data.events.length > 0) {
          this.lastEventTime = data.events[data.events.length - 1].timestamp;
        }
      }
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") return;

      this.handleConnectionError();
    }
  }

  private shouldProcessEvent(event: WebSocketEvent): boolean {
    // Filter by event type
    if (this.eventTypes && !this.eventTypes.has(event.type)) {
      return false;
    }

    // Filter by severity
    if (this.minSeverity && event.data?.severity) {
      const severityOrder = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"];
      const eventIndex = severityOrder.indexOf(event.data.severity as string);
      const minIndex = severityOrder.indexOf(this.minSeverity);
      if (eventIndex < minIndex) {
        return false;
      }
    }

    return true;
  }

  private flushBuffer(): void {
    if (this.eventBuffer.length === 0) return;

    // Sort by timestamp
    this.eventBuffer.sort(
      (a, b) =>
        new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    );

    // Emit batched events
    for (const event of this.eventBuffer) {
      this.onEvent?.(event);
    }

    this.eventBuffer = [];
  }

  private handleConnectionError(): void {
    this.stopPolling();
    this.setStatus("reconnecting");

    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error("Max reconnection attempts reached");
      this.setStatus("disconnected");
      return;
    }

    const delay = Math.min(
      1000 * Math.pow(2, this.reconnectAttempts),
      30000
    );

    console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts + 1})`);

    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempts++;
      this.startPolling();
    }, delay + Math.random() * 1000); // Add jitter
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}

/**
 * Hook-compatible function to create a WebSocket connection
 */
export function createWebSocketConnection(
  options: WebSocketOptions
): ResilientWebSocket {
  return new ResilientWebSocket(options);
}
