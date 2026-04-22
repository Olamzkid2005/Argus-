"use client";

import { useState, useEffect, useCallback } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import Sidebar from "@/components/ui-custom/Sidebar";
import CommandPalette from "@/components/ui-custom/CommandPalette";
import { applyThreePatch } from "@/lib/three-patch";

// Apply the global Three.js shim before any 3D components render
applyThreePatch();

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const pathname = usePathname();
  const router = useRouter();

  const isFullBleedPage = pathname === "/" || pathname.startsWith("/auth");

  // CMD+K handler
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCommandPaletteOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const handleNavigate = useCallback(
    (path: string) => {
      router.push(path);
    },
    [router]
  );

  return (
    <div className="min-h-screen bg-surface">
      {!isFullBleedPage && (
        <Sidebar onOpenCommandPalette={() => setCommandPaletteOpen(true)} />
      )}

      <main className={`${!isFullBleedPage ? "ml-64" : ""}`}>
        <AnimatePresence mode="wait">
          <motion.div
            key={pathname}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
          >
            {children}
          </motion.div>
        </AnimatePresence>
      </main>

      {commandPaletteOpen && (
        <CommandPalette
          onNavigate={handleNavigate}
          onClose={() => setCommandPaletteOpen(false)}
        />
      )}
    </div>
  );
}
