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
  HelpCircle,
  Terminal,
  Plus,
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

  return (
    <aside
      className="fixed left-0 top-0 h-full w-64 z-40 flex flex-col bg-white dark:bg-zinc-950 border-r border-gray-100 dark:border-zinc-800 shadow-xl"
    >
      {/* Brand */}
      <div className="flex items-center px-4 py-4 border-b border-gray-100 dark:border-zinc-800">
        <Link href="/dashboard" className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-[#6720FF] flex items-center justify-center shrink-0">
            <ShieldCheck size={18} className="text-white" />
          </div>
          <div>
            <h1 className="text-xl font-black tracking-tighter text-gray-900 dark:text-white leading-none">
              ARGUS
            </h1>
            <p className="font-headline uppercase tracking-widest text-[9px] font-bold text-gray-500 dark:text-gray-400 mt-0.5">
              SOC Infrastructure
            </p>
          </div>
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-3 space-y-0.5 overflow-y-auto">
        {navItems.map((item) => {
          const isActive = pathname === item.to || (item.to === "/dashboard" && pathname === "/");
          return (
            <Link
              key={item.to}
              href={item.to}
              className={`relative flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-200 group ${
                isActive
                  ? "bg-[#6720FF]/10 text-[#6720FF] font-bold"
                  : "text-gray-600 dark:text-gray-400 hover:text-[#6720FF] hover:bg-[#6720FF]/5"
              }`}
            >
              <item.icon
                size={18}
                className={`shrink-0 ${isActive ? "text-[#6720FF]" : "text-gray-400 dark:text-gray-500 group-hover:text-[#6720FF]"}`}
              />
              <span className="font-headline text-xs uppercase tracking-widest">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* AI Status */}
      <div className="px-4 py-2 border-t border-gray-100 dark:border-zinc-800">
        <AIStatusIndicator />
      </div>

      {/* Report Incident */}
      <div className="px-4 py-2">
        <button className="w-full py-2.5 bg-[#6720FF] text-white rounded-lg font-headline font-bold text-[10px] uppercase tracking-widest shadow-lg shadow-[#6720FF]/20 active:scale-95 transition-all flex items-center justify-center gap-2">
          <Plus size={14} />
          Report Incident
        </button>
      </div>

      {/* Bottom Actions */}
      <div className="px-4 py-2 border-t border-gray-100 dark:border-zinc-800 space-y-0.5">
        <button
          onClick={onOpenCommandPalette}
          className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-gray-500 dark:text-gray-400 hover:text-[#6720FF] hover:bg-[#6720FF]/5 transition-all duration-200"
        >
          <Command size={16} />
          <span className="font-headline text-[10px] uppercase tracking-widest flex-1 text-left">Command</span>
          <div className="flex gap-1">
            <kbd className="text-[8px] text-gray-400 dark:text-gray-500 border border-gray-200 dark:border-zinc-700 rounded px-1 py-0.5 font-mono">⌘</kbd>
            <kbd className="text-[8px] text-gray-400 dark:text-gray-500 border border-gray-200 dark:border-zinc-700 rounded px-1 py-0.5 font-mono">K</kbd>
          </div>
        </button>

        <Link
          href="#"
          className="flex items-center gap-3 px-3 py-2 rounded-lg text-gray-500 dark:text-gray-400 hover:text-[#6720FF] hover:bg-[#6720FF]/5 transition-all duration-200"
        >
          <HelpCircle size={16} />
          <span className="font-headline text-[10px] uppercase tracking-widest">Support</span>
        </Link>

        <Link
          href="#"
          className="flex items-center gap-3 px-3 py-2 rounded-lg text-gray-500 dark:text-gray-400 hover:text-[#6720FF] hover:bg-[#6720FF]/5 transition-all duration-200"
        >
          <Terminal size={16} />
          <span className="font-headline text-[10px] uppercase tracking-widest">Logs</span>
        </Link>

        {/* Theme Toggle */}
        <button
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-gray-500 dark:text-gray-400 hover:text-[#6720FF] hover:bg-[#6720FF]/5 transition-all duration-200"
        >
          {mounted && theme === "dark" ? (
            <>
              <Sun size={16} />
              <span className="font-headline text-[10px] uppercase tracking-widest">Light Mode</span>
            </>
          ) : (
            <>
              <Moon size={16} />
              <span className="font-headline text-[10px] uppercase tracking-widest">Dark Mode</span>
            </>
          )}
        </button>
      </div>

      {/* User */}
      <div className="px-4 py-3 border-t border-gray-100 dark:border-zinc-800 flex items-center gap-3">
        <div className="w-8 h-8 rounded-full bg-gray-100 dark:bg-zinc-800 flex items-center justify-center border-2 border-[#6720FF]/10 shrink-0">
          <span className="text-[10px] font-bold text-[#6720FF]">OP</span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-bold text-gray-900 dark:text-gray-100 truncate">Operator</div>
          <div className="text-[9px] text-gray-500 dark:text-gray-400 truncate font-mono uppercase">Admin Level</div>
        </div>
      </div>
    </aside>
  );
}