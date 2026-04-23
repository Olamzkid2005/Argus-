"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

export interface UseKeyboardShortcutsOptions {
  onToggleCommandPalette?: () => void;
  onExplainFinding?: () => void;
  onVerifyFinding?: () => void;
  onClose?: () => void;
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
