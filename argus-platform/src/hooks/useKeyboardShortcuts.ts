"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";

export interface UseKeyboardShortcutsOptions {
  onToggleCommandPalette?: () => void;
  onExplainFinding?: () => void;
  onVerifyFinding?: () => void;
  onClose?: () => void;
}

/** Generic shortcut descriptor used by useGlobalShortcuts */
interface Shortcut {
  key: string;
  ctrl?: boolean;
  shift?: boolean;
  alt?: boolean;
  action: () => void;
  description: string;
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName;
  return (
    tagName === "INPUT" ||
    tagName === "TEXTAREA" ||
    tagName === "SELECT" ||
    target.isContentEditable
  );
}

export function useKeyboardShortcuts(options: UseKeyboardShortcutsOptions = {}) {
  const router = useRouter();
  const [showHelp, setShowHelp] = useState(false);

  const optionsRef = useRef(options);
  optionsRef.current = options;

  const showHelpRef = useRef(showHelp);
  showHelpRef.current = showHelp;

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) {
        return;
      }

      const hasCtrlOrMeta = event.ctrlKey || event.metaKey;
      const hasAlt = event.altKey;

      // Cmd/Ctrl+K: Toggle command palette
      if (hasCtrlOrMeta && !hasAlt && event.key.toLowerCase() === "k") {
        event.preventDefault();
        optionsRef.current.onToggleCommandPalette?.();
        return;
      }

      // Cmd/Ctrl+N: Navigate to /engagements (New Scan)
      if (hasCtrlOrMeta && !hasAlt && event.key.toLowerCase() === "n") {
        event.preventDefault();
        router.push("/engagements");
        return;
      }

      // ?: Show keyboard shortcuts help modal
      if (event.key === "?" && !hasCtrlOrMeta && !hasAlt) {
        event.preventDefault();
        setShowHelp(true);
        return;
      }

      // Esc: Close modals/panels
      if (event.key === "Escape") {
        if (showHelpRef.current) {
          setShowHelp(false);
          return;
        }
        optionsRef.current.onClose?.();
        return;
      }

      // E: Explain selected finding (when on findings page and finding selected)
      if (!hasCtrlOrMeta && !hasAlt && event.key.toLowerCase() === "e") {
        event.preventDefault();
        if (optionsRef.current.onExplainFinding) {
          optionsRef.current.onExplainFinding();
        } else {
          window.dispatchEvent(new CustomEvent("shortcut:explain-finding"));
        }
        return;
      }

      // V: Verify selected finding (when on findings page and finding selected)
      if (!hasCtrlOrMeta && !hasAlt && event.key.toLowerCase() === "v") {
        event.preventDefault();
        if (optionsRef.current.onVerifyFinding) {
          optionsRef.current.onVerifyFinding();
        } else {
          window.dispatchEvent(new CustomEvent("shortcut:verify-finding"));
        }
        return;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [router]);

  return { showHelp, setShowHelp };
}

// ── Generic array-based shortcut registration (used by GlobalShortcuts) ──

/**
 * Register arbitrary keyboard shortcuts from an array of Shortcut descriptors.
 * Use `useGlobalShortcuts()` for the default set of navigation shortcuts.
 */
export function useShortcutList(shortcuts: Shortcut[]) {
  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) return;

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

/**
 * Predefined global navigation shortcuts:
 *   Ctrl+D → Dashboard
 *   Ctrl+E → Engagements
 *   Ctrl+F → Findings
 *   Ctrl+Shift+N → New Engagement
 *   /       → Focus search input
 */
export function useGlobalShortcuts() {
  const router = useRouter();

  const shortcuts: Shortcut[] = [
    { key: "d", ctrl: true, action: () => router.push("/dashboard"), description: "Go to Dashboard" },
    { key: "e", ctrl: true, action: () => router.push("/engagements"), description: "Go to Engagements" },
    { key: "f", ctrl: true, action: () => router.push("/findings"), description: "Go to Findings" },
    { key: "n", ctrl: true, shift: true, action: () => router.push("/engagements"), description: "New Engagement" },
    { key: "/", action: () => document.querySelector<HTMLInputElement>("input")?.focus(), description: "Search" },
  ];

  useShortcutList(shortcuts);
}
