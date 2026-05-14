"use client";

import { useState, useEffect, useRef } from "react";

interface CommandPaletteProps {
  onNavigate: (path: string) => void;
  onClose: () => void;
}

export function CommandPalette({ onNavigate, onClose }: CommandPaletteProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[2147483646] flex items-start justify-center pt-[20vh]">
      <div className="fixed inset-0 bg-black/50" onClick={onClose} />
      <div className="relative z-10 w-full max-w-lg bg-white dark:bg-gray-800 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 overflow-hidden">
        <input
          ref={inputRef}
          type="text"
          placeholder="Type a command..."
          className="w-full px-4 py-3 text-sm border-0 outline-none bg-transparent"
        />
      </div>
    </div>
  );
}
