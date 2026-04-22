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
  FileCode2,
  Server,
  Zap,
  HelpCircle,
  Terminal,
  Plus,
  PanelLeftClose,
} from "lucide-react";
import { AIStatusIndicator } from "./AIStatus";

interface SidebarProps {
  onOpenCommandPalette: () => void;
  onClose: () => void;
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

export default function Sidebar({ onOpenCommandPalette, onClose }: SidebarProps) {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  return (
    <aside className="fixed left-0 top-0 h-full w-64 z-40 flex flex-col bg-surface dark:bg-zinc-950 shadow-[40px_0_64px_-20px_rgba(103,32,255,0.06)] transition-transform duration-300 ease-in-out">
      {/* Brand */}
      <div className="flex items-center justify-between px-4 py-5">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-primary flex items-center justify-center">
            <ShieldCheck size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-black tracking-tighter text-on-surface dark:text-white font-headline">
              ARGUS
            </h1>
            <p className="font-headline uppercase tracking-widest text-[10px] font-bold text-on-surface-variant">
              SOC Infrastructure
            </p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[10px] font-semibold text-on-surface-variant hover:text-on-surface hover:bg-surface-container border border-outline-variant/30 hover:border-outline-variant/60 transition-all duration-200 group"
          aria-label="Close sidebar"
        >
          <PanelLeftClose size={16} className="group-hover:-translate-x-0.5 transition-transform duration-200" />
          <span className="hidden xl:inline">Collapse</span>
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-2 space-y-1">
        {navItems.map((item) => {
          const isActive = pathname === item.to || (item.to === "/dashboard" && pathname === "/");
          return (
            <Link
              key={item.to}
              href={item.to}
              className={`relative flex items-center gap-3 px-4 py-3 rounded-lg text-sm transition-all duration-200 group ${
                isActive
                  ? "bg-white dark:bg-zinc-900 text-primary shadow-sm font-bold"
                  : "text-on-surface-variant hover:text-primary hover:bg-primary/5"
              }`}
            >
              <item.icon
                size={20}
                className={`shrink-0 ${
                  isActive ? "text-primary" : "text-on-surface-variant group-hover:text-primary"
                }`}
              />
              <span className="font-headline text-xs uppercase tracking-widest">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* AI Status */}
      <div className="px-4 py-2 border-t border-outline-variant/20">
        <AIStatusIndicator />
      </div>

      {/* Report Incident */}
      <div className="px-4 py-3">
        <button className="w-full py-3 bg-gradient-to-r from-primary to-primary-container text-white rounded-lg font-headline font-bold text-xs uppercase tracking-widest shadow-lg shadow-primary/20 active:scale-95 transition-all flex items-center justify-center gap-2">
          <Plus size={16} />
          Report Incident
        </button>
      </div>

      {/* Bottom Actions */}
      <div className="px-4 py-3 border-t border-outline-variant/20 space-y-1">
        <button
          onClick={onOpenCommandPalette}
          className="w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-on-surface-variant hover:text-primary hover:bg-primary/5 transition-all duration-200"
        >
          <Command size={18} />
          <span className="font-headline text-xs uppercase tracking-widest flex-1 text-left">Command</span>
          <div className="flex gap-1">
            <kbd className="text-[9px] text-on-surface-variant border border-outline-variant rounded px-1 py-0.5 font-mono">
              ⌘
            </kbd>
            <kbd className="text-[9px] text-on-surface-variant border border-outline-variant rounded px-1 py-0.5 font-mono">
              K
            </kbd>
          </div>
        </button>

        <Link
          href="#"
          className="flex items-center gap-3 px-4 py-2.5 rounded-lg text-on-surface-variant hover:text-primary hover:bg-primary/5 transition-all duration-200"
        >
          <HelpCircle size={18} />
          <span className="font-headline text-xs uppercase tracking-widest">Support</span>
        </Link>

        <Link
          href="#"
          className="flex items-center gap-3 px-4 py-2.5 rounded-lg text-on-surface-variant hover:text-primary hover:bg-primary/5 transition-all duration-200"
        >
          <Terminal size={18} />
          <span className="font-headline text-xs uppercase tracking-widest">Logs</span>
        </Link>

        {/* Theme Toggle */}
        <button
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          className="w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-on-surface-variant hover:text-primary hover:bg-primary/5 transition-all duration-200"
        >
          {theme === "dark" ? (
            <>
              <Sun size={18} />
              <span className="font-headline text-xs uppercase tracking-widest">Light Mode</span>
            </>
          ) : (
            <>
              <Moon size={18} />
              <span className="font-headline text-xs uppercase tracking-widest">Dark Mode</span>
            </>
          )}
        </button>
      </div>

      {/* User */}
      <div className="px-4 py-4 border-t border-outline-variant/20 flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-surface-container-high flex items-center justify-center border-2 border-primary/10">
          <span className="text-xs font-bold text-primary">OP</span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-bold text-on-surface truncate">Operator</div>
          <div className="text-[10px] text-on-surface-variant truncate font-mono uppercase">Admin Level</div>
        </div>
      </div>
    </aside>
  );
}
