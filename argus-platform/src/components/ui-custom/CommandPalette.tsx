import { useState, useEffect, useRef, useCallback } from "react";
import { Search, Shield, Terminal, FileText, Settings, Activity, Users, AlertTriangle } from "lucide-react";

interface CommandItem {
  id: string;
  label: string;
  shortcut?: string;
  icon: React.ReactNode;
  action: () => void;
}

const commands: CommandItem[] = [
  { id: "dashboard", label: "Go to Dashboard", shortcut: "G D", icon: <Activity size={18} />, action: () => {} },
  { id: "findings", label: "View Findings", shortcut: "G F", icon: <AlertTriangle size={18} />, action: () => {} },
  { id: "engagements", label: "Active Engagements", shortcut: "G E", icon: <Shield size={18} />, action: () => {} },
  { id: "reports", label: "Generate Report", shortcut: "G R", icon: <FileText size={18} />, action: () => {} },
  { id: "terminal", label: "Open Terminal", shortcut: "G T", icon: <Terminal size={18} />, action: () => {} },
  { id: "team", label: "Team Management", icon: <Users size={18} />, action: () => {} },
  { id: "settings", label: "Settings", shortcut: "G S", icon: <Settings size={18} />, action: () => {} },
];

interface CommandPaletteProps {
  onNavigate?: (path: string) => void;
  onClose: () => void;
}

export default function CommandPalette({ onNavigate, onClose }: CommandPaletteProps) {
  const [search, setSearch] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = commands.filter((c) =>
    c.label.toLowerCase().includes(search.toLowerCase())
  );

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1) % Math.max(filtered.length, 1));
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 + Math.max(filtered.length, 1)) % Math.max(filtered.length, 1));
      }
      if (e.key === "Enter" && filtered[selectedIndex]) {
        const cmd = filtered[selectedIndex];
        if (cmd.id === "dashboard") onNavigate?.("/");
        if (cmd.id === "findings") onNavigate?.("/findings");
        if (cmd.id === "engagements") onNavigate?.("/engagements");
        if (cmd.id === "reports") onNavigate?.("/reports");
        if (cmd.id === "settings") onNavigate?.("/settings");
        onClose();
      }
    },
    [filtered, selectedIndex, onClose, onNavigate]
  );

  useEffect(() => {
    inputRef.current?.focus();
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [search]);

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[20vh]"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-xl" />

      {/* Palette */}
      <div
        className="relative w-full max-w-xl mx-4 rounded-lg border border-white/10 overflow-hidden"
        style={{
          background: "rgba(18, 18, 26, 0.8)",
          backdropFilter: "blur(24px)",
          boxShadow: "0 0 40px rgba(233, 255, 255, 0.05)",
        }}
      >
        {/* Search Input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-white/10">
          <Search size={18} className="text-text-secondary shrink-0" />
          <input
            ref={inputRef}
            type="text"
            placeholder="Type a command or search..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="flex-1 bg-transparent text-text-primary text-sm outline-none placeholder:text-text-secondary/50"
          />
          <kbd className="text-[10px] text-text-secondary border border-white/10 rounded px-1.5 py-0.5 font-mono">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div className="max-h-[320px] overflow-y-auto py-2">
          {filtered.length === 0 ? (
            <div className="px-4 py-8 text-center text-text-secondary text-sm">
              No results found for "{search}"
            </div>
          ) : (
            filtered.map((cmd, i) => (
              <button
                key={cmd.id}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors duration-150 ${
                  i === selectedIndex ? "bg-white/5" : "hover:bg-white/[0.02]"
                }`}
                onClick={() => {
                  if (cmd.id === "dashboard") onNavigate?.("/");
                  if (cmd.id === "findings") onNavigate?.("/findings");
                  if (cmd.id === "engagements") onNavigate?.("/engagements");
                  if (cmd.id === "reports") onNavigate?.("/reports");
                  if (cmd.id === "settings") onNavigate?.("/settings");
                  onClose();
                }}
              >
                <span className="text-text-secondary">{cmd.icon}</span>
                <span className="flex-1 text-sm text-text-primary">{cmd.label}</span>
                {cmd.shortcut && (
                  <div className="flex gap-1">
                    {cmd.shortcut.split(" ").map((key, j) => (
                      <kbd
                        key={j}
                        className="text-[10px] text-text-secondary border border-white/10 rounded px-1 py-0.5 font-mono"
                      >
                        {key}
                      </kbd>
                    ))}
                  </div>
                )}
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}