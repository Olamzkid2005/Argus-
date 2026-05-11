"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { log } from "@/lib/logger";

export interface ScannerActivity {
  id: string;
  tool_name: string;
  activity: string;
  status: "started" | "in_progress" | "completed" | "failed";
  target?: string;
  details?: string;
  items_found?: number;
  duration_ms?: number;
  created_at: string;
}

export interface UseScannerActivitiesOptions {
  engagementId: string | null;
  pollingInterval?: number;
  enabled?: boolean;
}

export interface UseScannerActivitiesReturn {
  activities: ScannerActivity[];
  isLoading: boolean;
  error: Error | null;
  refetch: () => void;
}

const STORAGE_KEY = (id: string) => `argus:activities:${id}`;

function loadStoredActivities(id: string): ScannerActivity[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY(id));
    if (raw) return JSON.parse(raw);
  } catch {
    // ignore parse errors
  }
  return [];
}

function saveStoredActivities(id: string, activities: ScannerActivity[]) {
  try {
    sessionStorage.setItem(STORAGE_KEY(id), JSON.stringify(activities.slice(0, 100)));
  } catch {
    // ignore storage quota errors
  }
}

/**
 * Hook for polling scanner activities from the database.
 * Provides persistent, historical visibility into what scanning tools did.
 * Activities are cached in sessionStorage to survive page navigation.
 */
export function useScannerActivities(
  options: UseScannerActivitiesOptions,
): UseScannerActivitiesReturn {
  const { engagementId, pollingInterval = 2000, enabled = true } = options;

  const [activities, setActivities] = useState<ScannerActivity[]>(() =>
    engagementId ? loadStoredActivities(engagementId) : [],
  );
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const mountedRef = useRef(true);
  const prevIdRef = useRef(engagementId);
  const consecutiveErrorsRef = useRef(0);
  const stoppedRef = useRef(false);
  const MAX_ERRORS = 5;

  // Reset stored data when engagementId changes
  useEffect(() => {
    if (prevIdRef.current !== engagementId) {
      prevIdRef.current = engagementId;
      setActivities(engagementId ? loadStoredActivities(engagementId) : []);
      consecutiveErrorsRef.current = 0;
      stoppedRef.current = false;
    }
  }, [engagementId]);

  // Persist activities to sessionStorage
  useEffect(() => {
    if (engagementId) {
      saveStoredActivities(engagementId, activities);
    }
  }, [engagementId, activities]);

  const fetchActivities = useCallback(async () => {
    if (!engagementId || !mountedRef.current) return;
    // Auto-recover from stopped state: allow retry after cooldown
    if (stoppedRef.current) {
      // Will naturally be reset if engagementId changes or refetch() called
      return;
    }

    try {
      const response = await fetch(
        `/api/engagement/${engagementId}/activities?limit=50`,
      );

      if (!response.ok) {
        // 4xx errors: stop polling immediately (access issue won't resolve)
        if (response.status >= 400 && response.status < 500) {
          stoppedRef.current = true;
          log.wsEvent("activities-access-denied", { engagementId, status: response.status });
          setError(new Error(`Access denied: ${response.status}`));
          return;
        }
        throw new Error(`Failed to fetch activities: ${response.status}`);
      }

      const data = await response.json();

      if (mountedRef.current) {
        consecutiveErrorsRef.current = 0;
        setActivities(data.activities || []);
        setError(null);
      }
    } catch (err) {
      if (mountedRef.current) {
        consecutiveErrorsRef.current += 1;
        if (consecutiveErrorsRef.current >= MAX_ERRORS) {
          stoppedRef.current = true;
          log.wsEvent("activities-polling-stopped", { engagementId });
          return;
        }
        // Reset errors counter on intermittent successes (handled at top of try)
        log.wsError("Scanner activities fetch failed", { error: String(err), engagementId });
        setError(err instanceof Error ? err : new Error(String(err)));
      }
    }
  }, [engagementId]);

  const refetch = useCallback(() => {
    // Allow refetch even if stopped (user explicitly retrying)
    stoppedRef.current = false;
    consecutiveErrorsRef.current = 0;
    log.wsEvent("refetchActivities", { engagementId });
    setIsLoading(true);
    fetchActivities().finally(() => {
      if (mountedRef.current) setIsLoading(false);
    });
  }, [fetchActivities, engagementId]);

  // Polling
  useEffect(() => {
    mountedRef.current = true;

    if (enabled && engagementId) {
      setIsLoading(true);
      fetchActivities().finally(() => {
        if (mountedRef.current) setIsLoading(false);
      });

      intervalRef.current = setInterval(() => {
        fetchActivities();
      }, pollingInterval);
    }

    return () => {
      mountedRef.current = false;
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [enabled, engagementId, pollingInterval, fetchActivities]);

  return { activities, isLoading, error, refetch };
}
