"use client";

import { useState, useEffect, useCallback, useRef } from "react";

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

/**
 * Hook for polling scanner activities from the database.
 * Provides persistent, historical visibility into what scanning tools did.
 */
export function useScannerActivities(
  options: UseScannerActivitiesOptions,
): UseScannerActivitiesReturn {
  const { engagementId, pollingInterval = 2000, enabled = true } = options;

  const [activities, setActivities] = useState<ScannerActivity[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const mountedRef = useRef(true);

  const fetchActivities = useCallback(async () => {
    if (!engagementId || !mountedRef.current) return;

    try {
      const response = await fetch(
        `/api/engagement/${engagementId}/activities?limit=50`,
      );

      if (!response.ok) {
        throw new Error(`Failed to fetch activities: ${response.status}`);
      }

      const data = await response.json();

      if (mountedRef.current) {
        setActivities(data.activities || []);
        setError(null);
      }
    } catch (err) {
      if (mountedRef.current) {
        setError(err instanceof Error ? err : new Error(String(err)));
      }
    }
  }, [engagementId]);

  const refetch = useCallback(() => {
    setIsLoading(true);
    fetchActivities().finally(() => {
      if (mountedRef.current) setIsLoading(false);
    });
  }, [fetchActivities]);

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
