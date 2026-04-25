"use client";

import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { usePathname, useRouter } from "next/navigation";
import { Menu, X } from "lucide-react";
import Sidebar from "@/components/ui-custom/Sidebar";
import { CommandPalette } from "@/components/ui-custom/CommandPalette";
import { KeyboardShortcutsHelp } from "@/components/ui-custom/KeyboardShortcutsHelp";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import OnboardingTour from "@/components/ui-custom/OnboardingTour";
import { applyThreePatch } from "@/lib/three-patch";

applyThreePatch();

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const pathname = usePathname();
  const router = useRouter();

  const isFullBleedPage = pathname === "/" || pathname.startsWith("/auth");

  const { showHelp, setShowHelp } = useKeyboardShortcuts({
    onToggleCommandPalette: () => setCommandPaletteOpen((prev) => !prev),
    onClose: () => {
      setCommandPaletteOpen(false);
      setSidebarOpen(false);
    },
  });

  // Cmd/Ctrl+B for sidebar toggle (not handled by the hook)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "b" && !isFullBleedPage) {
        e.preventDefault();
        setSidebarOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isFullBleedPage]);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    const win = window as Window & { toggleSidebar?: () => void };
    win.toggleSidebar = () => setSidebarOpen((prev) => !prev);
    return () => {
      delete win.toggleSidebar;
    };
  }, [mounted]);

  // Render the same structure on server and client to prevent hydration mismatches
  // Only the sidebar content is conditionally rendered based on state
  return (
    <div className="min-h-screen">
      <div
        className={`main-content ${!isFullBleedPage && sidebarOpen ? "lg:ml-64" : "ml-0"}`}
      >
        {children}
      </div>

      {mounted && !isFullBleedPage && (
        <>
          {createPortal(
            <button
              type="button"
              onClick={() => setSidebarOpen((prev) => !prev)}
              className="fixed top-4 right-4 z-[2147483647] p-3 rounded-xl bg-[#6720FF] text-white border-none cursor-pointer flex items-center justify-center w-12 h-12 shadow-lg shadow-purple-500/30 hover:bg-[#7c3aed] transition-colors"
              style={{
                position: "fixed",
                top: "1rem",
                right: "1rem",
                zIndex: 2147483647,
                pointerEvents: "auto",
              }}
              aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
              title={sidebarOpen ? "Close sidebar" : "Open sidebar"}
            >
              {sidebarOpen ? <X size={24} /> : <Menu size={24} />}
            </button>,
            document.body
          )}

          {sidebarOpen && (
            <Sidebar
              onOpenCommandPalette={() => setCommandPaletteOpen(true)}
              onClose={() => setSidebarOpen(false)}
            />
          )}
        </>
      )}

      {commandPaletteOpen && (
        <CommandPalette
          onNavigate={(path) => router.push(path)}
          onClose={() => setCommandPaletteOpen(false)}
        />
      )}

      <KeyboardShortcutsHelp open={showHelp} onOpenChange={setShowHelp} />
      <OnboardingTour />
    </div>
  );
}