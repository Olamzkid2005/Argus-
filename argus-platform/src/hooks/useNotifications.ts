"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { log } from "@/lib/logger";

export interface Notification {
  id: string;
  type: "scan_complete" | "finding" | "status_change" | "system";
  title: string;
  message: string;
  timestamp: string;
  read: boolean;
  engagementId?: string;
}

const STORAGE_KEY = "argus-notifications";
const MAX_NOTIFICATIONS = 50;

function loadNotifications(): Notification[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Notification[];
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    log.browser.error("useNotifications.loadNotifications", error);
    return [];
  }
}

function saveNotifications(notifications: Notification[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(notifications));
  } catch (error) {
    log.browser.error("useNotifications.saveNotifications", error);
  }
}

export interface UseNotificationsReturn {
  notifications: Notification[];
  unreadCount: number;
  addNotification: (notification: Omit<Notification, "id" | "timestamp" | "read">) => void;
  removeNotification: (id: string) => void;
  markAsRead: (id: string) => void;
  markAllAsRead: () => void;
  dismissAll: () => void;
}

export function useNotifications(): UseNotificationsReturn {
  const [notifications, setNotifications] = useState<Notification[]>(loadNotifications);
  const [mounted, setMounted] = useState(true);

  useEffect(() => {
    if (mounted) {
      saveNotifications(notifications);
    }
  }, [notifications, mounted]);

  const unreadCount = useMemo(
    () => notifications.filter((n) => !n.read).length,
    [notifications]
  );

  const addNotification = useCallback(
    (notification: Omit<Notification, "id" | "timestamp" | "read">) => {
      const newNotification: Notification = {
        ...notification,
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
        timestamp: new Date().toISOString(),
        read: false,
      };
      setNotifications((prev) => {
        const next = [newNotification, ...prev];
        return next.slice(0, MAX_NOTIFICATIONS);
      });
    },
    []
  );

  const removeNotification = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  const markAsRead = useCallback((id: string) => {
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, read: true } : n))
    );
  }, []);

  const markAllAsRead = useCallback(() => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  }, []);

  const dismissAll = useCallback(() => {
    setNotifications([]);
  }, []);

  return {
    notifications,
    unreadCount,
    addNotification,
    removeNotification,
    markAsRead,
    markAllAsRead,
    dismissAll,
  };
}
