"use client";

import React, { useState } from "react";
import {
  Bell,
  CheckCircle2,
  ShieldAlert,
  AlertTriangle,
  Info,
  X,
  CheckCheck,
  Inbox,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { motion, AnimatePresence } from "framer-motion";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useNotifications, Notification } from "@/hooks/useNotifications";
import { cn } from "@/lib/utils";

const typeConfig: Record<
  Notification["type"],
  { icon: React.ReactNode; color: string; bg: string }
> = {
  scan_complete: {
    icon: <CheckCircle2 className="size-4" />,
    color: "text-success",
    bg: "bg-success/10",
  },
  finding: {
    icon: <ShieldAlert className="size-4" />,
    color: "text-warning",
    bg: "bg-warning/10",
  },
  status_change: {
    icon: <Info className="size-4" />,
    color: "text-info",
    bg: "bg-info/10",
  },
  system: {
    icon: <AlertTriangle className="size-4" />,
    color: "text-error",
    bg: "bg-error/10",
  },
};

function NotificationItem({
  notification,
  onMarkAsRead,
  onDismiss,
}: {
  notification: Notification;
  onMarkAsRead: (id: string) => void;
  onDismiss: (id: string) => void;
}) {
  const config = typeConfig[notification.type];
  const relativeTime = formatDistanceToNow(new Date(notification.timestamp), {
    addSuffix: true,
  });

  return (
    <motion.div
      layout
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      className={cn(
        "group relative flex gap-3 rounded-lg border p-3 transition-colors",
        notification.read
          ? "border-outline-variant/30 bg-transparent"
          : "border-outline-variant/50 bg-surface-container/50 dark:bg-[#1A1A24]/50"
      )}
    >
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          config.bg,
          config.color
        )}
      >
        {config.icon}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <p
            className={cn(
              "text-sm font-medium",
              notification.read
                ? "text-on-surface-variant"
                : "text-on-surface"
            )}
          >
            {notification.title}
          </p>
          <button
            onClick={() => onDismiss(notification.id)}
            className="shrink-0 rounded p-0.5 text-on-surface-variant opacity-0 transition-opacity hover:bg-surface-container dark:hover:bg-[#1A1A24] group-hover:opacity-100"
            aria-label="Dismiss notification"
          >
            <X className="size-3.5" />
          </button>
        </div>
        <p className="mt-0.5 text-xs text-on-surface-variant line-clamp-2">
          {notification.message}
        </p>
        <div className="mt-1.5 flex items-center justify-between">
          <span className="text-[10px] text-on-surface-variant/70">
            {relativeTime}
          </span>
          {!notification.read && (
            <button
              onClick={() => onMarkAsRead(notification.id)}
              className="text-[10px] font-medium text-primary hover:underline"
            >
              Mark as read
            </button>
          )}
        </div>
      </div>
    </motion.div>
  );
}

export default function NotificationCenter() {
  const {
    notifications,
    unreadCount,
    markAsRead,
    removeNotification,
    markAllAsRead,
    dismissAll,
  } = useNotifications();
  const [open, setOpen] = useState(false);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          className="relative flex h-9 w-9 items-center justify-center rounded-lg border border-outline-variant dark:border-[#ffffff10] text-on-surface-variant transition-colors hover:bg-surface-container dark:hover:bg-[#1A1A24]"
          aria-label="Notifications"
        >
          <Bell className="size-[18px]" />
          {unreadCount > 0 && (
            <span className="absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-error px-1 text-[9px] font-bold text-white">
              {unreadCount > 99 ? "99+" : unreadCount}
            </span>
          )}
        </button>
      </PopoverTrigger>

      <PopoverContent
        align="end"
        sideOffset={8}
        className="w-96 p-0 border-outline-variant dark:border-[#ffffff10] bg-surface-container-lowest dark:bg-[#12121A]"
      >
        <div className="flex items-center justify-between border-b border-outline-variant/30 px-4 py-3">
          <h3 className="text-sm font-semibold text-on-surface">
            Notifications
          </h3>
          <div className="flex items-center gap-1">
            {unreadCount > 0 && (
              <button
                onClick={markAllAsRead}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary/10"
              >
                <CheckCheck className="size-3.5" />
                Mark all read
              </button>
            )}
            {notifications.length > 0 && (
              <button
                onClick={dismissAll}
                className="rounded-md px-2 py-1 text-xs font-medium text-on-surface-variant transition-colors hover:bg-surface-container dark:hover:bg-[#1A1A24]"
              >
                Clear all
              </button>
            )}
          </div>
        </div>

        {notifications.length === 0 ? (
          <div className="flex flex-col items-center justify-center px-6 py-10 text-center">
            <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-surface-container dark:bg-[#1A1A24]">
              <Inbox className="size-5 text-on-surface-variant" />
            </div>
            <p className="text-sm font-medium text-on-surface">No notifications</p>
            <p className="mt-1 text-xs text-on-surface-variant">
              You&apos;re all caught up
            </p>
          </div>
        ) : (
          <ScrollArea className="max-h-[400px]">
            <div className="flex flex-col gap-2 p-3">
              <AnimatePresence initial={false}>
                {notifications.map((notification) => (
                  <NotificationItem
                    key={notification.id}
                    notification={notification}
                    onMarkAsRead={markAsRead}
                    onDismiss={removeNotification}
                  />
                ))}
              </AnimatePresence>
            </div>
          </ScrollArea>
        )}
      </PopoverContent>
    </Popover>
  );
}
