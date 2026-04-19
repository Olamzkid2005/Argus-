"use client";

import { useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";

interface Shortcut {
  key: string;
  ctrl?: boolean;
  shift?: boolean;
  alt?: boolean;
  action: () => void;
  description: string;
}

export function useKeyboardShortcuts(shortcuts: Shortcut[]) {
  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      // Don't trigger shortcuts when typing in inputs
      const target = event.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable
      ) {
        return;
      }

      for (const shortcut of shortcuts) {
        const keyMatch = event.key.toLowerCase() === shortcut.key.toLowerCase();
        const ctrlMatch = shortcut.ctrl
          ? event.ctrlKey || event.metaKey
          : !event.ctrlKey && !event.metaKey;
        const shiftMatch = shortcut.shift ? event.shiftKey : !event.shiftKey;
        const altMatch = shortcut.alt ? event.altKey : !event.altKey;

        if (keyMatch && ctrlMatch && shiftMatch && altMatch) {
          event.preventDefault();
          shortcut.action();
          break;
        }
      }
    },
    [shortcuts],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);
}

// Predefined shortcuts
export function useGlobalShortcuts() {
  const router = useRouter();

  const shortcuts: Shortcut[] = [
    {
      key: "d",
      ctrl: true,
      action: () => router.push("/dashboard"),
      description: "Go to Dashboard",
    },
    {
      key: "e",
      ctrl: true,
      action: () => router.push("/engagements"),
      description: "Go to Engagements",
    },
    {
      key: "f",
      ctrl: true,
      action: () => router.push("/findings"),
      description: "Go to Findings",
    },
    {
      key: "n",
      ctrl: true,
      shift: true,
      action: () => router.push("/engagements"),
      description: "New Engagement",
    },
    {
      key: "/",
      action: () => document.querySelector<HTMLInputElement>("input")?.focus(),
      description: "Search",
    },
  ];

  useKeyboardShortcuts(shortcuts);
}
