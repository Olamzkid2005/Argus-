"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import {
  LayoutDashboard,
  ShieldCheck,
  Bug,
  FileBarChart,
  Settings,
  Command,
  Sun,
  Moon,
  Laptop,
  FileCode2,
  Server,
} from "lucide-react";
import { AIStatusIndicator } from "./AIStatus";

interface SidebarProps {
  onOpenCommandPalette: () => void;
}

const navItems = [
  { to: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/engagements", icon: ShieldCheck, label: "Engagements" },
  { to: "/findings", icon: Bug, label: "Findings" },
  { to: "/assets", icon: Server, label: "Assets" },
  { to: "/rules", icon: FileCode2, label: "Rules" },
  { to: "/reports", icon: FileBarChart, label: "Reports" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

export default function Sidebar({ onOpenCommandPalette }: SidebarProps) {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // Avoid hydration mismatch
  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  return (
    <aside className="fixed left-0 top-0 h-full w-[220px] z-40 flex flex-col border-r border-structural bg-surface">
      {/* Brand */}
      <div className="flex items-center gap-2.5 px-5 py-5 border-b border-structural">
        <div className="w-7 h-7 rounded-sm bg-surface border border-structural flex items-center justify-center">
          <ShieldCheck size={16} className="text-prism-cream" />
        </div>
        <span className="text-sm font-semibold tracking-wider text-text-primary uppercase font-mono">
          Argus SOC
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-3">
        {navItems.map((item) => {
          const isActive = pathname === item.to || (item.to === "/dashboard" && pathname === "/");
          return (
            <Link
              key={item.to}
              href={item.to}
              className={`relative flex items-center gap-3 px-5 py-2.5 text-sm transition-all duration-200 group ${
                isActive
                  ? "text-text-primary"
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              {isActive && (
                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[2px] h-5 bg-prism-cream" />
              )}
              <item.icon
                size={18}
                className={`shrink-0 ${
                  isActive ? "text-prism-cream" : "text-text-secondary group-hover:text-text-primary"
                }`}
              />
              <span className="font-mono text-xs uppercase tracking-wider">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* AI Status */}
      <div className="px-4 py-2 border-t border-structural">
        <AIStatusIndicator />
      </div>

      {/* Theme Toggle & Command Palette Trigger */}
      <div className="px-4 py-3 border-t border-structural space-y-2">
        <button
          onClick={onOpenCommandPalette}
          className="w-full flex items-center gap-2 px-3 py-2 rounded border border-structural text-text-secondary hover:text-text-primary hover:border-text-secondary/40 transition-all duration-200 bg-surface/30"
        >
          <Command size={14} />
          <span className="text-[10px] uppercase font-bold tracking-widest flex-1 text-left">Command Palette</span>
          <div className="flex gap-1">
            <kbd className="text-[9px] text-text-secondary border border-structural rounded px-1 py-0.5 font-mono">
              ⌘
            </kbd>
            <kbd className="text-[9px] text-text-secondary border border-structural rounded px-1 py-0.5 font-mono">
              K
            </kbd>
          </div>
        </button>

        <div className="flex p-0.5 rounded border border-structural bg-surface/10">
          {(['light', 'dark', 'system'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTheme(t)}
              className={`flex-1 flex justify-center py-1.5 rounded-sm transition-all ${
                theme === t 
                  ? "bg-surface shadow-sm text-text-primary" 
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              {t === 'light' && <Sun size={14} />}
              {t === 'dark' && <Moon size={14} />}
              {t === 'system' && <Laptop size={14} />}
            </button>
          ))}
        </div>
      </div>

      {/* User */}
      <div className="px-5 py-4 border-t border-structural flex items-center gap-3">
        <div className="w-7 h-7 rounded-full bg-surface flex items-center justify-center border border-structural">
          <span className="text-[10px] font-bold text-prism-cyan">OP</span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-bold text-text-primary truncate uppercase">Operator</div>
          <div className="text-[9px] text-text-secondary truncate uppercase font-mono">Admin Level</div>
        </div>
      </div>
    </aside>
  );
}