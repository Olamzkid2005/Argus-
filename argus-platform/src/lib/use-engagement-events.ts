/**
 * React Hook for Real-Time Engagement Events
 *
 * Provides a unified interface for receiving real-time updates
 * via polling (fallback) or WebSocket connection.
 *
 * Requirements: 31.5
 */

"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { WebSocketEvent } from "./websocket-events";

export interface UseEngagementEventsOptions {
  engagementId: string;
  pollingInterval?: number; // milliseconds, default 2000
  enabled?: boolean;
  onEvent?: (event: WebSocketEvent) => void;
  onError?: (error: Error) => void;
}

export interface UseEngagementEventsReturn {
  events: WebSocketEvent[];
  currentState: string | null;
  isConnected: boolean;
  error: Error | null;
  reconnect: () => void;
  clearEvents: () => void;
}

/**
 * Hook for subscribing to real-time engagement events
 *
 * Uses polling as the primary mechanism with WebSocket support
 * available when configured.
 */
export function useEngagementEvents(
  options: UseEngagementEventsOptions,
): UseEngagementEventsReturn {
  const {
    engagementId,
    pollingInterval = 2000,
    enabled = true,
    onEvent,
    onError,
  } = options;

  const [events, setEvents] = useState<WebSocketEvent[]>([]);
  const [currentState, setCurrentState] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const pollingRef = useRef<NodeJS.Timeout | null>(null);
  const lastTimestampRef = useRef<string | null>(null);
  const mountedRef = useRef(true);

  // Fetch events via polling
  const fetchEvents = useCallback(async () => {
    if (!mountedRef.current || !enabled) return;

    try {
      const params = new URLSearchParams({
        limit: "50",
        ...(lastTimestampRef.current && { since: lastTimestampRef.current }),
      });

      const response = await fetch(
        `/api/ws/engagement/${engagementId}/poll?${params}`,
      );

      if (!response.ok) {
        throw new Error(`Failed to fetch events: ${response.status}`);
      }

      const data = await response.json();

      if (mountedRef.current) {
        setIsConnected(true);
        setError(null);

        // Update current state
        if (data.current_state) {
          setCurrentState(data.current_state);
        }

        // Add new events
        if (data.events && data.events.length > 0) {
          setEvents((prev) => {
            // Deduplicate events
            const existingIds = new Set(
              prev.map((e) => `${e.type}-${e.timestamp}`),
            );
            const newEvents = data.events.filter(
              (e: WebSocketEvent) =>
                !existingIds.has(`${e.type}-${e.timestamp}`),
            );
            return [...newEvents, ...prev].slice(0, 100); // Keep last 100 events
          });

          // Update last timestamp
          const latestEvent = data.events[0];
          if (latestEvent) {
            lastTimestampRef.current = latestEvent.timestamp;
          }

          // Call onEvent callback for each new event
          if (onEvent) {
            data.events.forEach((event: WebSocketEvent) => {
              onEvent(event);
            });
          }
        }
      }
    } catch (err) {
      if (mountedRef.current) {
        const error = err instanceof Error ? err : new Error(String(err));
        setError(error);
        setIsConnected(false);
        onError?.(error);
      }
    }
  }, [engagementId, enabled, onEvent, onError]);

  // Start polling
  const startPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
    }

    // Initial fetch
    fetchEvents();

    // Set up polling interval
    pollingRef.current = setInterval(fetchEvents, pollingInterval);
  }, [fetchEvents, pollingInterval]);

  // Stop polling
  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  // Reconnect
  const reconnect = useCallback(() => {
    setError(null);
    lastTimestampRef.current = null;
    startPolling();
  }, [startPolling]);

  // Clear events
  const clearEvents = useCallback(() => {
    setEvents([]);
    lastTimestampRef.current = null;
  }, []);

  // Start/stop polling based on enabled state
  useEffect(() => {
    if (enabled) {
      startPolling();
    } else {
      stopPolling();
    }

    return () => {
      stopPolling();
    };
  }, [enabled, startPolling, stopPolling]);

  // Cleanup on unmount
  useEffect(() => {
    mountedRef.current = true;

    return () => {
      mountedRef.current = false;
      stopPolling();
    };
  }, [stopPolling]);

  return {
    events,
    currentState,
    isConnected,
    error,
    reconnect,
    clearEvents,
  };
}

/**
 * Hook for subscribing to specific event types
 */
export function useEngagementEventType<T extends WebSocketEvent["type"]>(
  engagementId: string,
  eventType: T,
  options?: Omit<UseEngagementEventsOptions, "engagementId" | "onEvent">,
) {
  const [typedEvents, setTypedEvents] = useState<
    Extract<WebSocketEvent, { type: T }>[]
  >([]);

  const handleEvent = useCallback(
    (event: WebSocketEvent) => {
      if (event.type === eventType) {
        setTypedEvents((prev) => [
          event as Extract<WebSocketEvent, { type: T }>,
          ...prev,
        ]);
      }
    },
    [eventType],
  );

  const result = useEngagementEvents({
    engagementId,
    onEvent: handleEvent,
    ...options,
  });

  return {
    ...result,
    events: typedEvents,
  };
}
