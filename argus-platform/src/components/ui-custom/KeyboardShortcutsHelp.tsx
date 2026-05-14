"use client";

interface KeyboardShortcutsHelpProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function KeyboardShortcutsHelp({ open, onOpenChange }: KeyboardShortcutsHelpProps) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[2147483646] flex items-center justify-center">
      <div className="fixed inset-0 bg-black/50" onClick={() => onOpenChange(false)} />
      <div className="relative z-10 bg-white dark:bg-gray-800 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 p-6 max-w-md w-full">
        <h2 className="text-lg font-semibold mb-4">Keyboard Shortcuts</h2>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span>Command Palette</span>
            <kbd className="px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-xs">⌘K</kbd>
          </div>
          <div className="flex justify-between">
            <span>Toggle Sidebar</span>
            <kbd className="px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-xs">⌘B</kbd>
          </div>
          <div className="flex justify-between">
            <span>Close</span>
            <kbd className="px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-xs">Esc</kbd>
          </div>
        </div>
      </div>
    </div>
  );
}
