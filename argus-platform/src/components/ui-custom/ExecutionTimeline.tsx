"use client";

import { useMemo } from "react";
import { Clock, CheckCircle2, XCircle, Loader2 } from "lucide-react";

interface TimelineEvent {
  id: string;
  name: string;
  tool?: string;
  status: "completed" | "failed" | "running" | "pending";
  startTime: string;
  endTime?: string;
  durationMs?: number;
}

interface ExecutionTimelineProps {
  events: TimelineEvent[];
  engagementStart: string;
  engagementEnd?: string;
}

const STATUS_CONFIG = {
  completed: { color: "#00FF88", icon: CheckCircle2 },
  failed: { color: "#FF4444", icon: XCircle },
  running: { color: "var(--prism-cyan)", icon: Loader2 },
  pending: { color: "var(--text-secondary)", icon: Clock },
};

export default function ExecutionTimeline({ events, engagementStart, engagementEnd }: ExecutionTimelineProps) {
  const { totalDuration, bars } = useMemo(() => {
    const start = new Date(engagementStart).getTime();
    const end = engagementEnd ? new Date(engagementEnd).getTime() : Date.now();
    const total = end - start;

    const sorted = [...events].sort((a, b) => new Date(a.startTime).getTime() - new Date(b.startTime).getTime());

    const computedBars = sorted.map((event) => {
      const evStart = new Date(event.startTime).getTime();
      const evEnd = event.endTime ? new Date(event.endTime).getTime() : end;
      const left = ((evStart - start) / total) * 100;
      const width = Math.max(((evEnd - evStart) / total) * 100, 0.5);
      return { ...event, left, width };
    });

    return { totalDuration: total, bars: computedBars };
  }, [events, engagementStart, engagementEnd]);

  const formatDuration = (ms: number) => {
    if (ms < 60000) return `${Math.round(ms / 1000)}s`;
    if (ms < 3600000) return `${Math.round(ms / 60000)}m`;
    return `${Math.round(ms / 3600000)}h ${Math.round((ms % 3600000) / 60000)}m`;
  };

  return (
    <div className="w-full bg-surface/20 border border-structural p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Clock size={14} className="text-prism-cyan" />
          <span className="text-[11px] font-bold uppercase tracking-widest text-text-secondary">Execution Timeline</span>
        </div>
        <span className="text-[10px] font-mono text-text-secondary">
          Total: {formatDuration(totalDuration)}
        </span>
      </div>

      {/* Gantt Bars */}
      <div className="space-y-2">
        {bars.map((bar) => {
          const config = STATUS_CONFIG[bar.status];
          const Icon = config.icon;
          return (
            <div key={bar.id} className="flex items-center gap-3">
              {/* Label */}
              <div className="w-32 shrink-0 flex items-center gap-2">
                <Icon size={12} style={{ color: config.color }} className={bar.status === "running" ? "animate-spin" : ""} />
                <span className="text-[10px] text-text-primary font-mono truncate">{bar.name}</span>
              </div>

              {/* Bar track */}
              <div className="flex-1 h-5 bg-void/50 relative border border-structural/30">
                {/* Bar */}
                <div
                  className="absolute top-0 h-full flex items-center px-1.5 overflow-hidden"
                  style={{
                    left: `${bar.left}%`,
                    width: `${bar.width}%`,
                    backgroundColor: `${config.color}15`,
                    borderLeft: `2px solid ${config.color}`,
                  }}
                >
                  {bar.width > 8 && (
                    <span className="text-[9px] font-mono truncate" style={{ color: config.color }}>
                      {bar.tool || bar.name}
                    </span>
                  )}
                </div>
              </div>

              {/* Duration */}
              <div className="w-16 text-right shrink-0">
                <span className="text-[9px] font-mono text-text-secondary">
                  {bar.durationMs ? formatDuration(bar.durationMs) : "—"}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Time axis */}
      <div className="flex items-center gap-3 mt-3 pt-2 border-t border-structural/30">
        <div className="w-32 shrink-0" />
        <div className="flex-1 relative h-4">
          {[0, 25, 50, 75, 100].map((pct) => (
            <div key={pct} className="absolute top-0" style={{ left: `${pct}%`, transform: "translateX(-50%)" }}>
              <div className="w-px h-1.5 bg-structural mb-0.5 mx-auto" />
              <span className="text-[9px] font-mono text-text-secondary/60">
                {pct}%
              </span>
            </div>
          ))}
        </div>
        <div className="w-16 shrink-0" />
      </div>
    </div>
  );
}
