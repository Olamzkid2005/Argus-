"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, ChevronUp, Target, FileSearch } from "lucide-react";

interface Finding {
  id: string;
  type: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
  confidence: number;
  endpoint: string;
  evidence: Record<string, unknown>;
  source_tool: string;
  created_at: string;
}

interface FindingGroup {
  check_id: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
  rule_name: string;
  count: number;
  findings: Finding[];
  endpoints: string[];
}

export function FindingGroupCard({
  group,
  getSeverityMeta,
}: {
  group: FindingGroup;
  getSeverityMeta: (s: string) => { color: string; bg: string };
}) {
  const [expanded, setExpanded] = useState(false);
  const meta = getSeverityMeta(group.severity);

  return (
    <motion.div
      layout
      className={`prism-glass rounded-2xl border-l-4 ${meta.bg} transition-all ${expanded ? "ring-2 ring-primary/20" : "hover:bg-white/5"}`}
      style={{ borderLeftColor: `var(--${group.severity.toLowerCase()}-color, currentColor)` }}
    >
      <div
        className="p-5 flex items-start justify-between gap-4 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-2">
            <div className={`px-2 py-0.5 rounded text-[10px] font-black uppercase tracking-widest ${meta.bg} ${meta.color}`}>
              {group.severity}
            </div>
            <h3 className="text-sm font-extrabold text-foreground tracking-tight truncate font-mono">
              {group.rule_name}
            </h3>
            <div className="px-2 py-0.5 rounded text-[10px] font-black uppercase tracking-widest bg-white/10 text-muted-foreground border border-border">
              {group.findings[0]?.source_tool}
            </div>
          </div>
          <div className="flex items-center gap-4 text-xs text-muted-foreground">
            <span className="font-black text-primary">{group.count} finding{group.count !== 1 ? "s" : ""}</span>
            <span className="opacity-40 font-mono">{group.findings[0]?.endpoint.split("/").slice(0, 3).join("/")}…</span>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <div className="flex -space-x-2">
            {group.endpoints.slice(0, 3).map((ep, i) => (
              <div
                key={i}
                className="h-7 w-7 rounded-full bg-white/10 border border-border flex items-center justify-center text-[9px] font-mono text-muted-foreground"
                title={ep}
              >
                {ep.split(".").pop()?.substring(0, 2) || "?"}
              </div>
            ))}
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
            className={`flex items-center justify-center h-8 w-8 rounded-xl transition-all ${expanded ? "bg-primary text-primary-foreground" : "bg-white/5 text-muted-foreground hover:text-foreground"}`}
          >
            {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="px-5 pb-5 pt-0 space-y-2 border-t border-border mt-1">
              {group.endpoints.slice(0, 10).map((ep, i) => (
                <div
                  key={i}
                  className="flex items-center gap-3 p-3 rounded-xl bg-white/5 hover:bg-white/10 transition-colors text-xs"
                >
                  <Target className="h-3 w-3 text-primary shrink-0" />
                  <code className="font-mono text-muted-foreground break-all flex-1">{ep}</code>
                  <span className="text-muted-foreground/40 font-mono text-[10px]">
                    {(group.findings[i]?.confidence * 100 || 0).toFixed(0)}%
                  </span>
                </div>
              ))}
              {group.endpoints.length > 10 && (
                <div className="text-center py-3 text-[10px] text-muted-foreground/40 font-mono">
                  +{group.endpoints.length - 10} more endpoints
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
