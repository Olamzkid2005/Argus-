"use client";

import { useState, useEffect, useCallback } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { PanelLeftOpen } from "lucide-react";
import Sidebar from "@/components/ui-custom/Sidebar";
import CommandPalette from "@/components/ui-custom/CommandPalette";
import { applyThreePatch } from "@/lib/three-patch";

// Apply the global Three.js shim before any 3D components render
applyThreePatch();

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
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
      {!isFullBleedPage && sidebarOpen && (
        <Sidebar
          onOpenCommandPalette={() => setCommandPaletteOpen(true)}
          onClose={() => setSidebarOpen(false)}
        />
      )}

      {/* Floating toggle button when sidebar is closed */}
      {!isFullBleedPage && !sidebarOpen && (
        <motion.button
          initial={{ opacity: 0, x: -10 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.2 }}
          onClick={() => setSidebarOpen(true)}
          className="fixed left-4 top-4 z-50 p-2.5 rounded-xl bg-surface dark:bg-zinc-900 border border-outline-variant/30 shadow-lg shadow-black/5 text-on-surface-variant hover:text-on-surface hover:border-primary/30 transition-all duration-200"
          aria-label="Open sidebar"
        >
          <PanelLeftOpen size={20} />
        </motion.button>
      )}

      <main
        className={`transition-all duration-300 ease-in-out ${
          !isFullBleedPage ? (sidebarOpen ? "lg:ml-64" : "ml-0") : ""
        }`}
      >
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
