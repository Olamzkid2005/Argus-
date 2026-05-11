"use client";

import { useGlobalShortcuts } from "@/hooks/useKeyboardShortcuts";

export function GlobalShortcuts() {
  useGlobalShortcuts();
  return null; // This component doesn't render anything
}
