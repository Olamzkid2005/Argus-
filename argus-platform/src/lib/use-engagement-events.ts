/**
 * React Hook for Real-Time Engagement Events
 *
 * Provides a unified interface for receiving real-time updates
 * via polling (fallback) or WebSocket connection.
 * Events are persisted to sessionStorage so they survive page navigation.
 *
 * Requirements: 31.5
 */

"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { log } from "@/lib/logger";
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

const STORAGE_KEY = (id: string) => `argus:events:${id}`;
const STATE_KEY = (id: string) => `argus:state:${id}`;

function loadStoredEvents(id: string): WebSocketEvent[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY(id));
    if (raw) return JSON.parse(raw);
  } catch {
    // ignore parse errors
  }
  return [];
}

function saveStoredEvents(id: string, events: WebSocketEvent[]) {
  try {
    sessionStorage.setItem(STORAGE_KEY(id), JSON.stringify(events.slice(0, 100)));
  } catch {
    // ignore storage quota errors
  }
}

function loadStoredState(id: string): string | null {
  try {
    return sessionStorage.getItem(STATE_KEY(id));
  } catch {
    return null;
  }
}

function saveStoredState(id: string, state: string) {
  try {
    sessionStorage.setItem(STATE_KEY(id), state);
  } catch {
    // ignore
  }
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

  const [events, setEvents] = useState<WebSocketEvent[]>(() =>
    loadStoredEvents(engagementId),
  );
  const [currentState, setCurrentState] = useState<string | null>(() =>
    loadStoredState(engagementId),
  );
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const pollingRef = useRef<NodeJS.Timeout | null>(null);
  const lastTimestampRef = useRef<string | null>(null);
  const mountedRef = useRef(true);
  const prevIdRef = useRef(engagementId);

  // Use refs for callbacks to avoid cascading re-creation of fetchEvents
  // when the consumer passes inline functions that change on every render.
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  // Reset stored data when engagementId changes
  useEffect(() => {
    if (prevIdRef.current !== engagementId) {
      prevIdRef.current = engagementId;
      setEvents(loadStoredEvents(engagementId));
      setCurrentState(loadStoredState(engagementId));
      lastTimestampRef.current = null;
    }
  }, [engagementId]);

  // Persist events to sessionStorage
  useEffect(() => {
    saveStoredEvents(engagementId, events);
  }, [engagementId, events]);

  // Persist state to sessionStorage
  useEffect(() => {
    if (currentState) {
      saveStoredState(engagementId, currentState);
    }
  }, [engagementId, currentState]);

  // Track consecutive errors for backoff
  const consecutiveErrorsRef = useRef(0);
  const maxErrorsBeforeStop = 5; // Stop polling after this many consecutive errors

  // Fetch events via polling
  const fetchEvents = useCallback(async () => {
    if (!mountedRef.current || !enabled) return;

    // Stop polling after too many consecutive errors (engagement likely deleted/forbidden)
    if (consecutiveErrorsRef.current >= maxErrorsBeforeStop) {
      if (consecutiveErrorsRef.current === maxErrorsBeforeStop) {
        log.wsEvent("polling-stopped", { engagementId, reason: `${maxErrorsBeforeStop} consecutive failures` });
        consecutiveErrorsRef.current = maxErrorsBeforeStop + 1; // Log only once
      }
      return;
    }

    try {
      const params = new URLSearchParams({
        limit: "50",
        ...(lastTimestampRef.current && { since: lastTimestampRef.current }),
      });

      const response = await fetch(
        `/api/ws/engagement/${engagementId}/poll?${params}`,
      );

      if (!response.ok) {
        // For 4xx errors (Forbidden/Unauthorized/Not Found), stop polling faster
        if (response.status >= 400 && response.status < 500) {
          consecutiveErrorsRef.current = maxErrorsBeforeStop; // Stop immediately
          log.wsEvent("polling-access-denied", { engagementId, status: response.status });
          setError(new Error(`Access denied: ${response.status}`));
          setIsConnected(false);
          onErrorRef.current?.(new Error(`Failed to fetch events: ${response.status}`));
          return;
        }
        throw new Error(`Failed to fetch events: ${response.status}`);
      }

      const data = await response.json();

      if (mountedRef.current) {
        // Reset error count on success
        consecutiveErrorsRef.current = 0;
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
          if (onEventRef.current) {
            data.events.forEach((event: WebSocketEvent) => {
              onEventRef.current!(event);
            });
          }
        }
      }
    } catch (err) {
      if (mountedRef.current) {
        consecutiveErrorsRef.current += 1;
        const error = err instanceof Error ? err : new Error(String(err));
        
        // Only log every few errors to avoid flooding
        if (consecutiveErrorsRef.current <= 3 || consecutiveErrorsRef.current % 5 === 0) {
          log.wsError("Engagement events fetch failed", { error: error.message, engagementId, attempt: consecutiveErrorsRef.current });
        }
        
        setError(error);
        setIsConnected(false);
        
        // Only call onError for the first error (avoids spam)
        if (consecutiveErrorsRef.current === 1) {
          onErrorRef.current?.(error);
        }
      }
    }
  }, [engagementId, enabled]);

  // Start polling
  const startPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
    }
    consecutiveErrorsRef.current = 0;
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
      log.wsDisconnect(engagementId);
    }
  }, [engagementId]);

  // Reconnect
  const reconnect = useCallback(() => {
    log.wsEvent("reconnect", { engagementId });
    setError(null);
    lastTimestampRef.current = null;
    startPolling();
  }, [startPolling, engagementId]);

  // Clear events
  const clearEvents = useCallback(() => {
    log.wsEvent("clearEvents", { engagementId });
    setEvents([]);
    lastTimestampRef.current = null;
    try {
      sessionStorage.removeItem(STORAGE_KEY(engagementId));
      sessionStorage.removeItem(STATE_KEY(engagementId));
    } catch {
      // ignore
    }
  }, [engagementId]);

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
