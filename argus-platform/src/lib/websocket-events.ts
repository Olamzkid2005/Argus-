/**
 * WebSocket Event Types for Real-Time Updates
 *
 * Requirements: 31.2, 31.3, 31.4
 */

export type WebSocketEventType =
  | "finding_discovered"
  | "state_transition"
  | "rate_limit_event"
  | "tool_executed"
  | "job_started"
  | "job_completed"
  | "error";

export interface WebSocketEvent {
  type: WebSocketEventType;
  engagement_id: string;
  timestamp: string;
  data: Record<string, unknown>;
}

export interface FindingEvent {
  type: "finding_discovered";
  engagement_id: string;
  timestamp: string;
  data: {
    finding_id: string;
    finding_type: string;
    severity: string;
    confidence: number;
    endpoint: string;
    source_tool: string;
  };
}

export interface StateTransitionEvent {
  type: "state_transition";
  engagement_id: string;
  timestamp: string;
  data: {
    from_state: string;
    to_state: string;
    reason: string | null;
  };
}

export interface RateLimitEvent {
  type: "rate_limit_event";
  engagement_id: string;
  timestamp: string;
  data: {
    domain: string;
    event_type: string;
    status_code: number | null;
    current_rps: number;
    message: string;
  };
}

export interface ToolExecutedEvent {
  type: "tool_executed";
  engagement_id: string;
  timestamp: string;
  data: {
    tool_name: string;
    duration_ms: number;
    success: boolean;
    findings_count: number;
  };
}

export interface JobStartedEvent {
  type: "job_started";
  engagement_id: string;
  timestamp: string;
  data: {
    job_type: string;
    target: string | null;
  };
}

export interface JobCompletedEvent {
  type: "job_completed";
  engagement_id: string;
  timestamp: string;
  data: {
    job_type: string;
    status: "success" | "failed";
    findings_count: number;
    duration_ms: number;
  };
}

export interface ErrorEvent {
  type: "error";
  engagement_id: string;
  timestamp: string;
  data: {
    error_message: string;
    error_code: string;
    context: Record<string, unknown>;
  };
}

/**
 * Redis channel names for WebSocket events
 */
export const WEBSOCKET_CHANNELS = {
  engagement: (engagementId: string) => `ws:engagement:${engagementId}`,
  allEngagements: "ws:engagements:all",
} as const;

/**
 * Publish an event to Redis for WebSocket distribution
 */
export async function publishWebSocketEvent(
  redis: import("ioredis").default,
  event: WebSocketEvent,
): Promise<void> {
  const channel = WEBSOCKET_CHANNELS.engagement(event.engagement_id);
  const message = JSON.stringify(event);
  await redis.publish(channel, message);
}
