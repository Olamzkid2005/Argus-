"use client";

/**
 * Findings Dashboard Page
 *
 * Displays vulnerability findings grouped by severity with filtering capabilities.
 *
 * Requirements: 32.1, 32.2, 32.3, 32.4, 32.5
 */

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  Filter,
  ShieldAlert,
  Target,
  Zap,
  ChevronDown,
  ChevronUp,
  Terminal,
  Activity,
  History,
  LayoutGrid,
  FileSearch,
  ArrowLeft,
} from "lucide-react";

// Types
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
  owasp_category?: string;
  cwe_id?: string;
}

interface ExecutionSpan {
  id: string;
  trace_id: string;
  span_name: string;
  duration_ms: number;
  created_at: string;
}

export default function FindingsDashboardPage() {
  const params = useParams();
  const engagementId = params.id as string;

  const [findings, setFindings] = useState<Finding[]>([]);
  const [timeline, setTimeline] = useState<ExecutionSpan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filter state
  const [selectedSeverities, setSelectedSeverities] = useState<string[]>([]);
  const [minConfidence, setMinConfidence] = useState<number>(0);
  const [selectedTools, setSelectedTools] = useState<string[]>([]);

  // Fetch findings
  useEffect(() => {
    if (!engagementId) return;

    const fetchFindings = async () => {
      try {
        setLoading(true);
        setError(null);

        // Build query parameters
        const params = new URLSearchParams();
        if (selectedSeverities.length > 0) {
          params.set("severity", selectedSeverities.join(","));
        }
        if (minConfidence > 0) {
          params.set("minConfidence", minConfidence.toString());
        }
        if (selectedTools.length > 0) {
          params.set("sourceTool", selectedTools.join(","));
        }

        const response = await fetch(
          `/api/engagement/${engagementId}/findings?${params.toString()}`,
        );

        if (!response.ok) {
          throw new Error("Failed to fetch findings");
        }

        const data = await response.json();
        setFindings(data.findings || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        setLoading(false);
      }
    };

    fetchFindings();
  }, [engagementId, selectedSeverities, minConfidence, selectedTools]);

  // Fetch timeline
  useEffect(() => {
    if (!engagementId) return;

    const fetchTimeline = async () => {
      try {
        const response = await fetch(
          `/api/engagement/${engagementId}/timeline`,
        );
        if (response.ok) {
          const data = await response.json();
          setTimeline(data.spans || []);
        }
      } catch (err) {
        console.error("Failed to fetch timeline:", err);
      }
    };

    fetchTimeline();
  }, [engagementId]);

  // Group findings by severity
  const groupedFindings = findings.reduce(
    (acc, finding) => {
      const severity = finding.severity;
      if (!acc[severity]) {
        acc[severity] = [];
      }
      acc[severity].push(finding);
      return acc;
    },
    {} as Record<string, Finding[]>,
  );

  // Get unique tools for filter
  const availableTools = Array.from(
    new Set(findings.map((f) => f.source_tool)),
  ).sort();

  // Severity order for display
  const severityOrder: Array<"CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO"> =
    ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];

  // Get severity meta
  const getSeverityMeta = (severity: string) => {
    switch (severity) {
      case "CRITICAL":
        return {
          color: "text-argus-magenta",
          bg: "bg-argus-magenta/10",
          border: "border-argus-magenta/20",
        };
      case "HIGH":
        return {
          color: "text-red-400",
          bg: "bg-red-400/10",
          border: "border-red-400/20",
        };
      case "MEDIUM":
        return {
          color: "text-argus-indigo",
          bg: "bg-argus-indigo/10",
          border: "border-argus-indigo/20",
        };
      case "LOW":
        return {
          color: "text-argus-cyan",
          bg: "bg-argus-cyan/10",
          border: "border-argus-cyan/20",
        };
      default:
        return {
          color: "text-muted-foreground",
          bg: "bg-muted/10",
          border: "border-border",
        };
    }
  };

  // Toggle severity filter
  const toggleSeverity = (severity: string) => {
    setSelectedSeverities((prev) =>
      prev.includes(severity)
        ? prev.filter((s) => s !== severity)
        : [...prev, severity],
    );
  };

  // Toggle tool filter
  const toggleTool = (tool: string) => {
    setSelectedTools((prev) =>
      prev.includes(tool) ? prev.filter((t) => t !== tool) : [...prev, tool],
    );
  };

  const router = useRouter();

  return (
    <div className="py-8 px-10">
      <div className="max-w-7xl mx-auto flex flex-col gap-8">
        {/* Header Block */}
        <div className="flex flex-col md:flex-row gap-6 items-center justify-between">
          <div className="flex flex-col gap-1">
            <div
              className="flex items-center gap-2 text-primary font-bold text-xs uppercase tracking-widest mb-1 cursor-pointer hover:opacity-80 transition-opacity"
              onClick={() => router.push("/dashboard")}
            >
              <ArrowLeft className="h-3 w-3" />
              Intelligence Center
            </div>
            <h1 className="text-3xl font-extrabold tracking-tight">
              Vulnerability Report
            </h1>
            <p className="text-sm text-muted-foreground font-medium flex items-center gap-2">
              <span className="font-mono text-primary/70">{engagementId}</span>
              <span className="opacity-30">•</span>
              Argus Analytic Core v2.0
            </p>
          </div>

          <div className="prism-glass p-2 rounded-2xl flex gap-1">
            <button className="px-4 py-2 bg-primary/10 text-primary rounded-xl font-bold text-xs flex items-center gap-2">
              <LayoutGrid className="h-3.5 w-3.5" /> Sector View
            </button>
            <button className="px-4 py-2 text-muted-foreground hover:bg-white/5 rounded-xl font-bold text-xs flex items-center gap-2">
              <History className="h-3.5 w-3.5" /> Timeline
            </button>
          </div>
        </div>

        {/* Filters & Stats Row */}
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
          {/* Filters Sidebar */}
          <div className="prism-glass p-6 rounded-3xl h-fit sticky top-24">
            <div className="flex items-center gap-2 mb-6">
              <Filter className="h-4 w-4 text-primary" />
              <h2 className="text-sm font-bold uppercase tracking-widest">
                Filters
              </h2>
            </div>

            <div className="space-y-6">
              <div>
                <label className="text-[10px] font-black uppercase text-muted-foreground tracking-widest block mb-3">
                  Severity Threshold
                </label>
                <div className="flex flex-col gap-2">
                  {severityOrder.map((severity) => {
                    const meta = getSeverityMeta(severity);
                    const isActive = selectedSeverities.includes(severity);
                    return (
                      <button
                        key={severity}
                        onClick={() => toggleSeverity(severity)}
                        className={`flex items-center justify-between px-3 py-2 rounded-xl border text-xs font-bold transition-all ${
                          isActive
                            ? `${meta.bg} ${meta.color} ${meta.border}`
                            : "bg-white/5 border-transparent text-muted-foreground hover:bg-white/10"
                        }`}
                      >
                        {severity}
                        {isActive && <Zap className="h-3 w-3" />}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <label className="text-[10px] font-black uppercase text-muted-foreground tracking-widest block mb-4">
                  Min. Confidence ({minConfidence}%)
                </label>
                <input
                  type="range"
                  min="0"
                  max="100"
                  step="5"
                  value={minConfidence}
                  onChange={(e) => setMinConfidence(parseInt(e.target.value))}
                  className="w-full h-1.5 bg-secondary rounded-lg appearance-none cursor-pointer accent-primary"
                />
              </div>

              {availableTools.length > 0 && (
                <div>
                  <label className="text-[10px] font-black uppercase text-muted-foreground tracking-widest block mb-3">
                    Detection Sources
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {availableTools.map((tool) => (
                      <button
                        key={tool}
                        onClick={() => toggleTool(tool)}
                        className={`px-3 py-1.5 rounded-lg border text-[10px] font-bold transition-all ${
                          selectedTools.includes(tool)
                            ? "bg-argus-indigo/20 border-argus-indigo/30 text-argus-indigo"
                            : "bg-white/5 border-transparent text-muted-foreground"
                        }`}
                      >
                        {tool}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Main Content Area */}
          <div className="lg:col-span-3 flex flex-col gap-8">
            {/* Summary Cards */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              {severityOrder.map((severity) => {
                const meta = getSeverityMeta(severity);
                const count = groupedFindings[severity]?.length || 0;
                return (
                  (count > 0 || !loading) && (
                    <div
                      key={severity}
                      className={`prism-glass p-4 rounded-2xl border-l-4 ${meta.border.split(" ")[0].replace("border-", "border-l-")}`}
                    >
                      <p className="text-[10px] font-black text-muted-foreground uppercase tracking-widest mb-1">
                        {severity}
                      </p>
                      <p className={`text-2xl font-extrabold ${meta.color}`}>
                        {count}
                      </p>
                    </div>
                  )
                );
              })}
            </div>

            {/* Findings List */}
            {loading ? (
              <div className="h-64 flex flex-col items-center justify-center gap-4 opacity-50">
                <div className="prism-scanner w-12 h-12" />
                <p className="text-sm font-bold animate-pulse uppercase tracking-[0.2em]">
                  Analyzing Trace Logs...
                </p>
              </div>
            ) : error ? (
              <div className="prism-glass p-8 rounded-3xl border-red-500/20 text-center">
                <ShieldAlert className="h-8 w-8 text-red-500 mx-auto mb-4" />
                <h3 className="text-red-500 font-bold mb-1">
                  Analytic Core Failure
                </h3>
                <p className="text-sm text-muted-foreground">{error}</p>
              </div>
            ) : (
              <div className="flex flex-col gap-10">
                {severityOrder.map((severity) => {
                  const severityFindings = groupedFindings[severity] || [];
                  if (severityFindings.length === 0) return null;
                  const meta = getSeverityMeta(severity);

                  return (
                    <section key={severity}>
                      <div className="flex items-center gap-4 mb-4">
                        <div
                          className={`h-px flex-1 bg-gradient-to-r from-transparent to-border`}
                        />
                        <h2
                          className={`text-xs font-black uppercase tracking-[0.3em] ${meta.color}`}
                        >
                          {severity} DISCOVERY ({severityFindings.length})
                        </h2>
                        <div
                          className={`h-px flex-1 bg-gradient-to-l from-transparent to-border`}
                        />
                      </div>
                      <div className="grid grid-cols-1 gap-4">
                        {severityFindings.map((finding) => (
                          <FindingCard key={finding.id} finding={finding} />
                        ))}
                      </div>
                    </section>
                  );
                })}

                {findings.length === 0 && (
                  <div className="prism-glass p-12 rounded-3xl text-center opacity-60">
                    <FileSearch className="h-10 w-10 text-muted-foreground mx-auto mb-4" />
                    <p className="text-muted-foreground font-medium">
                      No intelligence matches the filtered parameters.
                    </p>
                  </div>
                )}
              </div>
            )}

            {/* Timeline Sector */}
            {timeline.length > 0 && (
              <div className="prism-glass rounded-3xl overflow-hidden border-primary/10">
                <div className="px-8 py-5 border-b border-border flex items-center justify-between bg-white/5">
                  <div className="flex items-center gap-3">
                    <Activity className="h-5 w-5 text-primary" />
                    <h2 className="text-sm font-bold uppercase tracking-widest">
                      Execution Trace
                    </h2>
                  </div>
                </div>
                <div className="p-4 grid grid-cols-1 gap-2 overflow-y-auto max-h-[400px]">
                  {timeline.map((span, i) => (
                    <div
                      key={span.id}
                      className="flex items-center gap-4 p-3 rounded-xl hover:bg-white/5 transition-colors group"
                    >
                      <div className="text-[10px] font-mono text-muted-foreground/40 w-8">
                        {i + 1}.
                      </div>
                      <div className="flex-1">
                        <p className="text-xs font-bold text-foreground group-hover:text-primary transition-colors uppercase tracking-tight">
                          {span.span_name}
                        </p>
                        <p className="text-[10px] text-muted-foreground font-mono">
                          {new Date(span.created_at).toLocaleTimeString()}
                        </p>
                      </div>
                      <div className="text-[10px] font-black px-3 py-1 rounded-full bg-primary/10 text-primary border border-primary/20">
                        {span.duration_ms}ms
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Finding Card Component
 *
 * Requirements: 32.3, 32.4
 */
function FindingCard({ finding }: { finding: Finding }) {
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
                CVSS{" "}
                <span className="text-argus-magenta tracking-widest">
                  {finding.cvss_score.toFixed(1)}
                </span>
              </div>
            )}
            {finding.cwe_id && (
              <div className="flex items-center gap-1.5 text-[10px] font-bold text-muted-foreground bg-white/5 px-2 py-1 rounded-lg uppercase tracking-widest">
                {finding.cwe_id}
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
                  Timestamp: {new Date(finding.created_at).toLocaleString()}
                </p>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
