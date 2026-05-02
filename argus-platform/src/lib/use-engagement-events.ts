/**
 * React Hook for Real-Time Engagement Events
 *
 * Provides a unified interface for receiving real-time updates
 * via SSE (primary) with polling as fallback.
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
  pollingInterval?: number; // milliseconds, default 2000 (used only in fallback)
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
 * Uses SSE (Server-Sent Events) as the primary transport with
 * automatic fallback to polling if SSE fails or is unavailable.
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

  // SSE refs
  const eventSourceRef = useRef<EventSource | null>(null);
  const useSseRef = useRef(true); // Toggle to fallback

  // Polling refs
  const pollingRef = useRef<NodeJS.Timeout | null>(null);
  const lastTimestampRef = useRef<string | null>(null);

  const mountedRef = useRef(true);
  const prevIdRef = useRef(engagementId);

  // Use refs for callbacks to avoid cascading re-creation
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
      useSseRef.current = true; // Reset SSE attempt on new engagement
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

  // ── SSE connection ──
  const startSse = useCallback(() => {
    if (!mountedRef.current || !enabled) return;

    try {
      const source = new EventSource(`/api/stream/${engagementId}`);

      source.onopen = () => {
        if (mountedRef.current) {
          setIsConnected(true);
          setError(null);
          log.wsConnect(engagementId);
        }
      };

      source.onmessage = (e: MessageEvent) => {
        if (!mountedRef.current) return;

        try {
          const raw: Record<string, unknown> = JSON.parse(e.data);

          // Skip internal/control events
          if (raw.type === "__connected__" || raw.type === "__heartbeat__") return;

          const event = raw as unknown as WebSocketEvent;

          setEvents((prev) => {
            const next = [event as WebSocketEvent, ...prev].slice(0, 100);
            saveStoredEvents(engagementId, next);
            return next;
          });

          if (event.type === "state_transition" && event.data?.to_state) {
            setCurrentState(event.data.to_state as string);
            saveStoredState(engagementId, event.data.to_state as string);
          }

          onEventRef.current?.(event as WebSocketEvent);
        } catch {
          // ignore parse errors
        }
      };

      source.onerror = () => {
        if (!mountedRef.current) return;

        // SSE connection failed — fall back to polling
        log.wsError("SSE connection failed, falling back to polling", {
          engagementId,
        });
        source.close();
        eventSourceRef.current = null;
        useSseRef.current = false;
        setIsConnected(false);
        startPollingFallback();
      };

      eventSourceRef.current = source;

      // Handle abort (e.g., React strict mode double-mount)
      _registerCleanup(() => {
        if (eventSourceRef.current) {
          eventSourceRef.current.close();
          eventSourceRef.current = null;
        }
      });
    } catch (err) {
      // EventSource constructor threw — fall back to polling
      log.wsError("SSE init failed, falling back to polling", {
        error: String(err),
        engagementId,
      });
      useSseRef.current = false;
      startPollingFallback();
    }
  }, [engagementId, enabled]);

  // Track consecutive errors for backoff
  const consecutiveErrorsRef = useRef(0);
  const maxErrorsBeforeStop = 5;
  let _cleanupFns: Array<() => void> = [];

  function _registerCleanup(fn: () => void) {
    _cleanupFns.push(fn);
  }

  // ── Polling fallback ──
  const fetchEvents = useCallback(async () => {
    if (!mountedRef.current || !enabled) return;

    if (consecutiveErrorsRef.current >= maxErrorsBeforeStop) {
      if (consecutiveErrorsRef.current === maxErrorsBeforeStop) {
        log.wsEvent("polling-stopped", {
          engagementId,
          reason: `${maxErrorsBeforeStop} consecutive failures`,
        });
        consecutiveErrorsRef.current = maxErrorsBeforeStop + 1;
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
        if (response.status >= 400 && response.status < 500) {
          consecutiveErrorsRef.current = maxErrorsBeforeStop;
          log.wsEvent("polling-access-denied", {
            engagementId,
            status: response.status,
          });
          setError(new Error(`Access denied: ${response.status}`));
          setIsConnected(false);
          onErrorRef.current?.(new Error(`Failed to fetch events: ${response.status}`));
          return;
        }
        throw new Error(`Failed to fetch events: ${response.status}`);
      }

      const data = await response.json();

      if (mountedRef.current) {
        consecutiveErrorsRef.current = 0;
        setIsConnected(true);
        setError(null);

        if (data.current_state) {
          setCurrentState(data.current_state);
        }

        if (data.events && data.events.length > 0) {
          setEvents((prev) => {
            const existingIds = new Set(
              prev.map((e) => `${e.type}-${e.timestamp}`),
            );
            const newEvents = data.events.filter(
              (e: WebSocketEvent) =>
                !existingIds.has(`${e.type}-${e.timestamp}`),
            );
            return [...newEvents, ...prev].slice(0, 100);
          });

          const latestEvent = data.events[0];
          if (latestEvent) {
            lastTimestampRef.current = latestEvent.timestamp;
          }

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

        if (consecutiveErrorsRef.current <= 3 || consecutiveErrorsRef.current % 5 === 0) {
          log.wsError("Engagement events fetch failed", {
            error: error.message,
            engagementId,
            attempt: consecutiveErrorsRef.current,
          });
        }

        setError(error);
        setIsConnected(false);

        if (consecutiveErrorsRef.current === 1) {
          onErrorRef.current?.(error);
        }
      }
    }
  }, [engagementId, enabled]);

  const startPollingFallback = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
    }
    consecutiveErrorsRef.current = 0;
    fetchEvents();
    pollingRef.current = setInterval(fetchEvents, pollingInterval);
  }, [fetchEvents, pollingInterval]);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
      log.wsDisconnect(engagementId);
    }
  }, [engagementId]);

  // ── Start connection ──
  useEffect(() => {
    if (enabled) {
      if (useSseRef.current) {
        startSse();
      } else {
        startPollingFallback();
      }
    }

    return () => {
      // Cleanup SSE
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      stopPolling();
      _cleanupFns = [];
    };
  }, [enabled, startSse, startPollingFallback, stopPolling]);

  // Cleanup on unmount
  useEffect(() => {
    mountedRef.current = true;

    return () => {
      mountedRef.current = false;
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      stopPolling();
    };
  }, [stopPolling]);

  // Reconnect
  const reconnect = useCallback(() => {
    log.wsEvent("reconnect", { engagementId });
    setError(null);
    lastTimestampRef.current = null;
    useSseRef.current = true; // Try SSE again

    // Close existing connections
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    stopPolling();

    // Restart with SSE
    startSse();
  }, [engagementId, startSse, stopPolling]);

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
