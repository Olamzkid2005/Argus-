"use client";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Keyboard, Command, CornerDownLeft, Search, CheckCircle2, Brain, HelpCircle, X } from "lucide-react";

interface KeyboardShortcutsHelpProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface ShortcutItem {
  keys: string[];
  action: string;
  icon: React.ReactNode;
}

const shortcuts: ShortcutItem[] = [
  {
    keys: ["Ctrl", "K"],
    action: "Toggle command palette",
    icon: <Search size={14} />,
  },
  {
    keys: ["Ctrl", "N"],
    action: "New Scan — navigate to engagements",
    icon: <Command size={14} />,
  },
  {
    keys: ["E"],
    action: "Explain selected finding",
    icon: <Brain size={14} />,
  },
  {
    keys: ["V"],
    action: "Verify selected finding",
    icon: <CheckCircle2 size={14} />,
  },
  {
    keys: ["?"],
    action: "Show keyboard shortcuts help",
    icon: <HelpCircle size={14} />,
  },
  {
    keys: ["Esc"],
    action: "Close modals / panels",
    icon: <X size={14} />,
  },
];

function ShortcutKey({ label }: { label: string }) {
  return (
    <kbd className="inline-flex items-center justify-center px-2 py-1 rounded-md bg-surface-container-high dark:bg-surface-container border border-outline-variant dark:border-outline/30 text-xs font-mono font-medium text-on-surface min-w-[28px] shadow-sm">
      {label}
    </kbd>
  );
}

export function KeyboardShortcutsHelp({ open, onOpenChange }: KeyboardShortcutsHelpProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="bg-background dark:bg-[#0A0A0F] border border-outline-variant dark:border-outline/30 sm:max-w-md"
        showCloseButton
      >
        <DialogHeader>
          <div className="flex items-center gap-2 mb-1">
            <Keyboard size={18} className="text-primary" />
            <DialogTitle className="text-lg font-semibold text-on-surface tracking-tight font-headline">
              Keyboard Shortcuts
            </DialogTitle>
          </div>
          <DialogDescription className="text-sm text-on-surface-variant font-body">
            Speed up your workflow with these global shortcuts.
          </DialogDescription>
        </DialogHeader>

        <div className="mt-4 space-y-2">
          {shortcuts.map((shortcut, index) => (
            <div
              key={index}
              className="flex items-center justify-between px-3 py-2.5 rounded-lg bg-surface dark:bg-surface-container-low border border-outline-variant/50 dark:border-outline/20 hover:border-primary/20 transition-all duration-200"
            >
              <div className="flex items-center gap-3">
                <span className="text-primary/80">{shortcut.icon}</span>
                <span className="text-sm text-on-surface font-body">
                  {shortcut.action}
                </span>
              </div>
              <div className="flex items-center gap-1">
                {shortcut.keys.map((key, keyIndex) => (
                  <span key={keyIndex} className="flex items-center gap-1">
                    <ShortcutKey label={key} />
                    {keyIndex < shortcut.keys.length - 1 && (
                      <span className="text-on-surface-variant/60 text-xs">
                        +
                      </span>
                    )}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="mt-4 pt-3 border-t border-outline-variant dark:border-outline/30">
          <div className="flex items-center gap-2 text-xs text-on-surface-variant/70 font-body">
            <CornerDownLeft size={12} />
            <span>Shortcuts are disabled while typing in inputs or textareas.</span>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
