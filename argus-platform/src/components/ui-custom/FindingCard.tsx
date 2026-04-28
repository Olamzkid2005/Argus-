"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Target,
  ChevronDown,
  ChevronUp,
  Terminal,
  History,
} from "lucide-react";

interface Finding {
  id: string;
  engagement_id: string;
  type: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
  confidence: number;
  endpoint: string;
  evidence: Record<string, unknown>;
  source_tool: string;
  created_at: string;
  repro_steps?: string[];
  cvss_score?: number;
  cvss_vector?: string;
  cve_id?: string;
  owasp_category?: string;
  cwe_id?: string;
}

/**
 * Finding Card Component
 *
 * Requirements: 32.3, 32.4
 */
function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function FindingCard({ finding }: { finding: Finding }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <motion.div
      layout
      className={`prism-glass rounded-2xl border-none transition-all ${expanded ? "ring-2 ring-primary/20" : "hover:bg-white/5"}`}
    >
      <div className="p-5 flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-2">
            <h3 className="text-sm font-extrabold text-foreground uppercase tracking-tight truncate">
              {finding.type}
            </h3>
            <div
              className={`px-2 py-0.5 rounded text-[10px] font-black uppercase tracking-widest bg-primary/10 text-primary border border-primary/20`}
            >
              {finding.source_tool}
            </div>
          </div>
          <p className="text-[11px] font-mono text-muted-foreground mb-3 break-all flex items-center gap-2">
            <Target className="h-3 w-3 text-primary" />
            {finding.endpoint}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5 text-[10px] font-bold text-muted-foreground bg-white/5 px-2 py-1 rounded-lg">
              Confidence{" "}
              <span className="text-primary tracking-widest">
                {(finding.confidence * 100).toFixed(0)}%
              </span>
            </div>
            {finding.cvss_score && (
              <div className="flex items-center gap-1.5 text-[10px] font-bold text-muted-foreground bg-white/5 px-2 py-1 rounded-lg">
                <a
                  href={`https://nvd.nist.gov/vuln/detail/${finding.cve_id || 'UNKNOWN'}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-argus-magenta transition-colors"
                  onClick={(e) => e.stopPropagation()}
                >
                  CVSS
                </a>
                <span className="text-argus-magenta tracking-widest">
                  {finding.cvss_score.toFixed(1)}
                </span>
                {finding.cvss_vector && (
                  <span className="text-[9px] font-mono text-muted-foreground/60 ml-1">
                    ({finding.cvss_vector})
                  </span>
                )}
              </div>
            )}
            {finding.cwe_id && (
              <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest">
                <a
                  href={`https://cwe.mitre.org/data/definitions/${finding.cwe_id.replace('CWE-', '')}.html`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-argus-amber hover:text-argus-amber/80 bg-argus-amber/10 px-2 py-1 rounded-lg border border-argus-amber/20 hover:border-argus-amber/40 transition-all flex items-center gap-1"
                  onClick={(e) => e.stopPropagation()}
                >
                  {finding.cwe_id}
                  <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                    <polyline points="15 3 21 3 21 9" />
                    <line x1={5} y1={5} x2={21} y2={21} />
                  </svg>
                </a>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    if (finding.cwe_id) navigator.clipboard.writeText(finding.cwe_id);
                  }}
                  className="p-1 hover:bg-white/10 rounded transition-colors"
                  title="Copy CWE ID"
                >
                  <svg className="h-3 w-3 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <rect x={9} y={9} width={13} height={13} rx={2} ry={2} />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                </button>
              </div>
            )}
          </div>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className={`flex items-center justify-center h-10 w-10 rounded-xl transition-all ${expanded ? "bg-primary text-primary-foreground" : "bg-white/5 text-muted-foreground hover:text-foreground"}`}
        >
          {expanded ? (
            <ChevronUp className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
        </button>
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="px-5 pb-5 pt-0 space-y-5 border-t border-border mt-1">
              {/* Evidence Sector */}
              {finding.evidence && Object.keys(finding.evidence).length > 0 && (
                <div className="mt-4">
                  <div className="flex items-center gap-2 mb-3">
                    <Terminal className="h-3.5 w-3.5 text-primary" />
                    <h4 className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">
                      Digital Evidence
                    </h4>
                  </div>
                  <pre className="text-[11px] font-mono bg-black/40 p-4 rounded-xl border border-border text-muted-foreground leading-relaxed overflow-x-auto">
                    {JSON.stringify(finding.evidence, null, 2)}
                  </pre>
                </div>
              )}

              {/* Reproduction Sector */}
              {finding.repro_steps && finding.repro_steps.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <History className="h-3.5 w-3.5 text-primary" />
                    <h4 className="text-[10px] font-black uppercase text-muted-foreground tracking-widest">
                      Proof of Concept Steps
                    </h4>
                  </div>
                  <div className="space-y-2">
                    {finding.repro_steps.map((step, index) => (
                      <div
                        key={index}
                        className="flex gap-3 items-start text-xs text-muted-foreground bg-white/5 p-3 rounded-xl"
                      >
                        <span className="text-primary font-black font-mono">
                          {index + 1}.
                        </span>
                        {step}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Metadata Footer */}
              <div className="flex items-center justify-between pt-4 border-t border-border opacity-40">
                <p className="text-[9px] font-mono uppercase font-bold tracking-widest">
                  Trace ID: {finding.id}
                </p>
                <p className="text-[9px] font-mono uppercase font-bold tracking-widest">
                  Timestamp: {relativeTime(finding.created_at)}
                </p>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
