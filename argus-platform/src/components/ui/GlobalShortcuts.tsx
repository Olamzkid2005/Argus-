"use client";

import { useGlobalShortcuts } from "@/lib/useKeyboardShortcuts";

export function GlobalShortcuts() {
  useGlobalShortcuts();
  return null; // This component doesn't render anything
}
