"use client";

import { Terminal, CheckCircle2, XCircle, Loader2, Activity } from "lucide-react";
import { ScannerActivity } from "@/lib/use-scanner-activities";

interface ScannerActivityPanelProps {
  activities: ScannerActivity[];
  isLoading?: boolean;
}

const TOOL_COLORS: Record<string, string> = {
  amass: "text-prism-cyan",
  naabu: "text-orange-400",
  httpx: "text-green-400",
  katana: "text-purple-400",
  ffuf: "text-pink-400",
  whatweb: "text-yellow-400",
  nikto: "text-red-400",
  gau: "text-blue-400",
  waybackurls: "text-indigo-400",
  nuclei: "text-prism-cream",
  dalfox: "text-rose-400",
  sqlmap: "text-emerald-400",
};

function StatusIcon({ status }: { status: string }) {
  if (status === "completed") {
    return <CheckCircle2 size={12} className="text-green-400 shrink-0" />;
  }
  if (status === "failed") {
    return <XCircle size={12} className="text-red-400 shrink-0" />;
  }
  if (status === "started") {
    return <Loader2 size={12} className="text-prism-cyan animate-spin shrink-0" />;
  }
  return <Activity size={12} className="text-text-secondary shrink-0" />;
}

export default function ScannerActivityPanel({
  activities,
  isLoading = false,
}: ScannerActivityPanelProps) {
  if (activities.length === 0 && !isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-10 text-text-secondary/40 gap-3">
        <Terminal size={24} />
        <p className="text-[10px] font-mono uppercase tracking-widest">
          No scanner activity yet
        </p>
      </div>
    );
  }

  return (
    <div className="max-h-[420px] overflow-y-auto space-y-1 pr-1">
      {isLoading && activities.length === 0 && (
        <div className="flex items-center justify-center py-6">
          <Loader2 size={16} className="animate-spin text-text-secondary" />
        </div>
      )}

      {activities.map((activity) => {
        const colorClass = TOOL_COLORS[activity.tool_name] || "text-text-secondary";
        const isRunning = activity.status === "started" || activity.status === "in_progress";

        return (
          <div
            key={activity.id}
            className={`group flex items-start gap-2.5 px-3 py-2 border border-transparent hover:border-structural/50 hover:bg-surface/20 transition-all ${
              isRunning ? "bg-prism-cyan/5 border-prism-cyan/10" : ""
            }`}
          >
            <StatusIcon status={activity.status} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-0.5">
                <span className={`text-[10px] font-bold font-mono uppercase tracking-wider ${colorClass}`}>
                  {activity.tool_name}
                </span>
                {activity.items_found !== null && activity.items_found !== undefined && (
                  <span className="text-[10px] font-mono text-text-secondary">
                    {activity.items_found} found
                  </span>
                )}
                {activity.duration_ms !== null && activity.duration_ms !== undefined && activity.duration_ms > 0 && (
                  <span className="text-[10px] font-mono text-text-secondary/60">
                    {Math.round(activity.duration_ms / 1000)}s
                  </span>
                )}
              </div>
              <p className="text-[11px] text-text-primary leading-snug truncate">
                {activity.activity}
              </p>
              {activity.target && (
                <p className="text-[10px] text-text-secondary/60 font-mono mt-0.5 truncate">
                  {activity.target}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
