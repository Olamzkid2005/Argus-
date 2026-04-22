"use client";

import { useState, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Menu, X } from "lucide-react";
import Sidebar from "@/components/ui-custom/Sidebar";
import CommandPalette from "@/components/ui-custom/CommandPalette";
import { applyThreePatch } from "@/lib/three-patch";

applyThreePatch();

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const pathname = usePathname();
  const router = useRouter();

  const isFullBleedPage = pathname === "/" || pathname.startsWith("/auth");

  // Cmd+K for command palette
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCommandPaletteOpen((prev) => !prev);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "b" && !isFullBleedPage) {
        e.preventDefault();
        setSidebarOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isFullBleedPage]);

  return (
    <div className="min-h-screen">
      {/* Toggle button - simple unconditional rendering */}
      {!isFullBleedPage && (
        <button
          onClick={() => setSidebarOpen((prev) => !prev)}
          className="fixed top-4 right-4 z-[99999] p-3 rounded-xl bg-[#6720FF] text-white border-none cursor-pointer flex items-center justify-center w-12 h-12 shadow-lg shadow-purple-500/30 hover:bg-[#7c3aed] transition-colors"
          aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
        >
          {sidebarOpen ? <X size={24} /> : <Menu size={24} />}
        </button>
      )}

      {/* Sidebar */}
      {!isFullBleedPage && sidebarOpen && (
        <Sidebar
          onOpenCommandPalette={() => setCommandPaletteOpen(true)}
          onClose={() => setSidebarOpen(false)}
        />
      )}

      {/* Main content */}
      <div className={`min-h-screen ${!isFullBleedPage && sidebarOpen ? "lg:ml-64" : "ml-0"}`}>
        {children}
      </div>

      {commandPaletteOpen && (
        <CommandPalette
          onNavigate={(path) => router.push(path)}
          onClose={() => setCommandPaletteOpen(false)}
        />
      )}
    </div>
  );
}