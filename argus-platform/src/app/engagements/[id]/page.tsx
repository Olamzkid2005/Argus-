"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { useParams, useRouter } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { motion, AnimatePresence } from "framer-motion";
import { log } from "@/lib/logger";
import {
  ArrowLeft,
  Shield,
  Globe,
  GitBranch,
  AlertTriangle,
  Loader2,
  Target,
  Clock,
  StopCircle,
  Trash2,
  RefreshCw,
  Activity,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Brain,
  Sparkles,
} from "lucide-react";
import { useEngagementEvents } from "@/lib/use-engagement-events";
import type { AgentDecisionEvent } from "@/lib/websocket-events";

interface Engagement {
  id: string;
  target_url: string;
  status: string;
  scan_type: string;
  created_at: string;
  completed_at: string | null;
  scan_aggressiveness: string;
  authorized_scope: Record<string, unknown>;
  max_cycles?: number;
  current_cycles?: number;
  current_depth?: number;
}

interface Finding {
  id: string;
  type: string;
  severity: string;
  endpoint: string;
  source_tool: string;
  verified: boolean;
  created_at: string;
}

interface TimelineEvent {
  id: string;
  event_type: string;
  message: string;
  created_at: string;
}

const STATUS_COLORS: Record<string, string> = {
  created: "text-yellow-500 bg-yellow-500/10 border-yellow-500/30",
  recon: "text-blue-500 bg-blue-500/10 border-blue-500/30",
  scanning: "text-purple-500 bg-purple-500/10 border-purple-500/30",
  analyzing: "text-indigo-500 bg-indigo-500/10 border-indigo-500/30",
  reporting: "text-cyan-500 bg-cyan-500/10 border-cyan-500/30",
  complete: "text-green-500 bg-green-500/10 border-green-500/30",
  failed: "text-error bg-error/10 border-error/30",
  paused: "text-yellow-500 bg-yellow-500/10 border-yellow-500/30",
};

const SEVERITY_COLORS: Record<string, string> = {
  CRITICAL: "text-error bg-error/10 border-error/30",
  HIGH: "text-orange-500 bg-orange-500/10 border-orange-500/30",
  MEDIUM: "text-yellow-500 bg-yellow-500/10 border-yellow-500/30",
  LOW: "text-green-500 bg-green-500/10 border-green-500/30",
  INFO: "text-blue-500 bg-blue-500/10 border-blue-500/30",
};

const SEVERITY_BADGE: Record<string, string> = {
  CRITICAL: "text-red-500 bg-red-500/10 border-red-500/30",
  HIGH: "text-orange-500 bg-orange-500/10 border-orange-500/30",
  MEDIUM: "text-yellow-500 bg-yellow-500/10 border-yellow-500/30",
  LOW: "text-blue-400 bg-blue-400/10 border-blue-400/30",
  INFO: "text-gray-400 bg-gray-400/10 border-gray-400/30",
};

export default function EngagementDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();
  const engagementId = params.id as string;

  const [engagement, setEngagement] = useState<Engagement | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [stoppingId, setStoppingId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isRescanning, setIsRescanning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Real-time events for agent reasoning feed
  const { events } = useEngagementEvents({
    engagementId,
    enabled: status === "authenticated" && !!engagementId,
    pollingInterval: 2000,
  });

  // Filter and sort agent decisions
  const agentDecisions = useMemo(
    () =>
      (events as AgentDecisionEvent[])
        .filter((e) => e.type === "agent_decision")
        .sort((a, b) => b.data.iteration - a.data.iteration)
        .slice(0, 20),
    [events],
  );

  useEffect(() => {
    log.pageMount("EngagementDetail");
    return () => log.pageUnmount("EngagementDetail");
  }, []);

  useEffect(() => {
    if (status === "unauthenticated") signIn();
  }, [status, router]);

  const fetchEngagement = useCallback(async () => {
    try {
      const res = await fetch(`/api/engagement/${engagementId}`);
      if (res.ok) {
        const data = await res.json();
        setEngagement(data.engagement);
        setError(null);
      } else {
        const body = await res.text();
        setError(body || "Failed to load engagement");
      }
    } catch {
      setError("Failed to load engagement");
    } finally {
      setIsLoading(false);
    }
  }, [engagementId]);

  const fetchFindings = useCallback(async () => {
    try {
      const res = await fetch(`/api/engagement/${engagementId}/findings`);
      if (res.ok) {
        const data = await res.json();
        setFindings(data.findings || []);
      }
    } catch { /* findings optional */ }
  }, [engagementId]);

  const fetchTimeline = useCallback(async () => {
    try {
      const res = await fetch(`/api/engagement/${engagementId}/timeline`);
      if (res.ok) {
        const data = await res.json();
        setTimeline(data.spans || data.events || data.timeline || []);
      }
    } catch { /* timeline optional */ }
  }, [engagementId]);

  useEffect(() => {
    if (status !== "authenticated" || !engagementId) return;
    fetchEngagement();
    fetchFindings();
    fetchTimeline();
  }, [status, engagementId, fetchEngagement, fetchFindings, fetchTimeline]);

  // Poll engagement status every 5s while active
  useEffect(() => {
    if (!engagement || ["complete", "failed", "paused"].includes(engagement.status)) return;
    const interval = setInterval(() => {
      fetchEngagement();
      fetchFindings();
      fetchTimeline();
    }, 5000);
    return () => clearInterval(interval);
  }, [engagement?.status, fetchEngagement, fetchFindings, fetchTimeline, engagement]);

  const handleStop = async () => {
    if (!confirm("Stop this scan?")) return;
    setStoppingId(engagementId);
    try {
      const res = await fetch(`/api/engagement/${engagementId}/stop`, { method: "POST" });
      if (res.ok) {
        showToast("success", "Scan stopped");
        fetchEngagement();
      } else {
        const data = await res.json().catch(() => ({}));
        showToast("error", data.error || "Failed to stop scan");
      }
    } catch {
      showToast("error", "Failed to stop scan");
    } finally {
      setStoppingId(null);
    }
  };

  const handleRescan = async () => {
    setIsRescanning(true);
    try {
      const res = await fetch(`/api/engagement/${engagementId}/rescan`, { method: "POST" });
      if (res.ok) {
        showToast("success", "Rescan triggered");
        fetchEngagement();
      } else {
        const data = await res.json().catch(() => ({}));
        showToast("error", data.error || "Failed to rescan");
      }
    } catch {
      showToast("error", "Failed to rescan");
    } finally {
      setIsRescanning(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm("Delete this engagement permanently?")) return;
    setIsDeleting(true);
    try {
      const res = await fetch(`/api/engagement/${engagementId}/delete`, { method: "DELETE" });
      if (res.ok) {
        showToast("success", "Engagement deleted");
        router.push("/engagements");
      } else {
        showToast("error", "Failed to delete engagement");
      }
    } catch {
      showToast("error", "Failed to delete engagement");
    } finally {
      setIsDeleting(false);
    }
  };

  if (status === "loading" || isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background dark:bg-[#0A0A0F]">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!session) return null;

  if (error && !engagement) {
    return (
      <div className="min-h-screen px-6 py-6 bg-background dark:bg-[#0A0A0F]">
        <div className="flex flex-col items-center justify-center pt-24 gap-4">
          <AlertCircle size={48} className="text-error" />
          <h2 className="text-xl font-semibold text-on-surface">Engagement Not Found</h2>
          <p className="text-sm text-on-surface-variant">{error}</p>
          <button
            onClick={() => router.push("/engagements")}
            className="px-4 py-2 bg-primary text-on-primary text-xs font-bold uppercase tracking-widest rounded-lg"
          >
            Back to Engagements
          </button>
        </div>
      </div>
    );
  }

  const statusCfg = STATUS_COLORS[engagement?.status || "created"] || STATUS_COLORS.created;

  return (
    <div className="min-h-screen px-6 py-6 bg-background dark:bg-[#0A0A0F] font-body">
      {/* Header */}
      <div className="mb-6">
        <button
          onClick={() => router.push("/engagements")}
          className="flex items-center gap-1.5 text-[11px] font-mono text-on-surface-variant hover:text-on-surface transition-colors mb-4"
        >
          <ArrowLeft size={14} />
          Back to Engagements
        </button>
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Shield size={18} className="text-primary" />
              <span className="text-[11px] font-mono text-on-surface-variant tracking-widest uppercase">
                Engagement Detail
              </span>
              <span className={`text-[10px] font-mono px-2 py-0.5 rounded-md border ${statusCfg}`}>
                {engagement?.status?.toUpperCase() || "UNKNOWN"}
              </span>
            </div>
            <h1 className="text-3xl font-semibold text-on-surface dark:text-white tracking-tight font-headline">
              {engagement?.target_url || "Engagement"}
            </h1>
            <p className="text-sm text-on-surface-variant mt-1">
              {engagement?.scan_type === "repo" ? "Repository Scan" : "Web Application Scan"}
              {engagement?.scan_aggressiveness ? ` · ${engagement.scan_aggressiveness} aggressiveness` : ""}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {engagement && !["complete", "failed", "paused"].includes(engagement.status) && (
              <button
                onClick={handleStop}
                disabled={stoppingId === engagementId}
                className="flex items-center gap-2 px-4 py-2 bg-error/10 border border-error/30 text-error text-[10px] font-bold uppercase tracking-widest rounded-lg hover:bg-error/20 transition-all disabled:opacity-50"
              >
                {stoppingId === engagementId ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <StopCircle size={12} />
                )}
                Stop Scan
              </button>
            )}
            {engagement && ["complete", "failed", "paused"].includes(engagement.status) && (
              <button
                onClick={handleRescan}
                disabled={isRescanning}
                className="flex items-center gap-2 px-4 py-2 bg-primary/10 border border-primary/30 text-primary text-[10px] font-bold uppercase tracking-widest rounded-lg hover:bg-primary/20 transition-all disabled:opacity-50"
              >
                {isRescanning ? (
                  <Loader2 size={12} className="animate-spin" />
                ) : (
                  <RefreshCw size={12} />
                )}
                Rescan
              </button>
            )}
            <button
              onClick={handleDelete}
              disabled={isDeleting}
              className="flex items-center gap-2 px-4 py-2 bg-surface-container border border-outline-variant text-on-surface-variant text-[10px] font-bold uppercase tracking-widest rounded-lg hover:text-error hover:border-error/30 transition-all disabled:opacity-50"
            >
              {isDeleting ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Trash2 size={12} />
              )}
              Delete
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Left column — Engagement Info */}
        <div className="col-span-12 lg:col-span-4 space-y-4">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-5"
          >
            <h3 className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-4 font-headline">
              Details
            </h3>
            <div className="space-y-3">
              <div>
                <span className="text-[10px] font-mono text-on-surface-variant block">Status</span>
                <span className={`text-xs font-mono font-bold mt-0.5 inline-block px-2 py-0.5 rounded border ${statusCfg}`}>
                  {engagement?.status?.toUpperCase() || "-"}
                </span>
              </div>
              <div>
                <span className="text-[10px] font-mono text-on-surface-variant block">Target</span>
                <span className="text-sm text-on-surface mt-0.5 block truncate">{engagement?.target_url || "-"}</span>
              </div>
              <div>
                <span className="text-[10px] font-mono text-on-surface-variant block">Type</span>
                <span className="text-xs text-on-surface mt-0.5 block capitalize">{engagement?.scan_type || "-"}</span>
              </div>
              <div>
                <span className="text-[10px] font-mono text-on-surface-variant block">Aggressiveness</span>
                <span className="text-xs text-on-surface mt-0.5 block capitalize">{engagement?.scan_aggressiveness || "-"}</span>
              </div>
              <div>
                <span className="text-[10px] font-mono text-on-surface-variant block">Created</span>
                <span className="text-xs text-on-surface mt-0.5 block">
                  {engagement?.created_at ? new Date(engagement.created_at).toLocaleString() : "-"}
                </span>
              </div>
              {engagement?.completed_at && (
                <div>
                  <span className="text-[10px] font-mono text-on-surface-variant block">Completed</span>
                  <span className="text-xs text-on-surface mt-0.5 block">
                    {new Date(engagement.completed_at).toLocaleString()}
                  </span>
                </div>
              )}
            </div>
          </motion.div>

          {/* Summary Stats */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-5"
          >
            <h3 className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest mb-4 font-headline">
              Summary
            </h3>
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-surface-container dark:bg-[#1A1A24] rounded-lg p-3 border border-outline-variant dark:border-[#ffffff08]">
                <div className="text-[10px] font-mono text-on-surface-variant uppercase tracking-wider">Findings</div>
                <div className="text-xl font-headline font-bold text-on-surface">{findings.length}</div>
              </div>
              <div className="bg-surface-container dark:bg-[#1A1A24] rounded-lg p-3 border border-outline-variant dark:border-[#ffffff08]">
                <div className="text-[10px] font-mono text-on-surface-variant uppercase tracking-wider">Critical</div>
                <div className="text-xl font-headline font-bold text-error">
                  {findings.filter(f => f.severity === "CRITICAL").length}
                </div>
              </div>
              <div className="bg-surface-container dark:bg-[#1A1A24] rounded-lg p-3 border border-outline-variant dark:border-[#ffffff08]">
                <div className="text-[10px] font-mono text-on-surface-variant uppercase tracking-wider">High</div>
                <div className="text-xl font-headline font-bold text-orange-500">
                  {findings.filter(f => f.severity === "HIGH").length}
                </div>
              </div>
              <div className="bg-surface-container dark:bg-[#1A1A24] rounded-lg p-3 border border-outline-variant dark:border-[#ffffff08]">
                <div className="text-[10px] font-mono text-on-surface-variant uppercase tracking-wider">Verified</div>
                <div className="text-xl font-headline font-bold text-green-500">
                  {findings.filter(f => f.verified).length}
                </div>
              </div>
            </div>
          </motion.div>
        </div>

        {/* Right column — Findings + Timeline */}
        <div className="col-span-12 lg:col-span-8 space-y-4">
          {/* Findings Section */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 }}
            className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-5"
          >
            <div className="flex items-center gap-2 mb-4">
              <AlertTriangle size={14} className="text-primary" />
              <h3 className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest font-headline">
                Findings
              </h3>
            </div>
            {findings.length === 0 ? (
              <div className="py-8 text-center">
                <p className="text-[11px] font-mono text-on-surface-variant/40 uppercase tracking-widest">
                  No findings yet
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {(() => {
                  // Group findings by type
                  const groups: Record<string, Finding[]> = {};
                  for (const f of findings) {
                    const key = f.type;
                    if (!groups[key]) groups[key] = [];
                    groups[key].push(f);
                  }
                  return Object.entries(groups).map(([type, items]) => {
                    // Count severities in this group
                    const sevCounts: Record<string, number> = {};
                    for (const f of items) {
                      sevCounts[f.severity] = (sevCounts[f.severity] || 0) + 1;
                    }
                    const worstSev = Object.keys(sevCounts).reduce((a, b) => {
                      const order = ["CRITICAL","HIGH","MEDIUM","LOW","INFO"];
                      return order.indexOf(a) <= order.indexOf(b) ? a : b;
                    }, Object.keys(sevCounts)[0] || "INFO");
                    const dotColor = worstSev === "CRITICAL" ? "bg-error" : worstSev === "HIGH" ? "bg-orange-500" : worstSev === "MEDIUM" ? "bg-yellow-500" : worstSev === "LOW" ? "bg-blue-400" : "bg-green-500";
                    return (
                      <div key={type} className="rounded-lg border border-outline-variant dark:border-[#ffffff10] overflow-hidden bg-surface-container dark:bg-[#1A1A24]">
                        {/* Group Header */}
                        <div className="flex items-center justify-between px-3 py-2 bg-surface-container-high dark:bg-[#2A2A35] border-b border-outline-variant dark:border-[#ffffff08]">
                          <div className="flex items-center gap-2">
                            <div className={`w-2 h-2 rounded-full ${dotColor}`} />
                            <span className="text-xs font-bold text-on-surface font-headline uppercase">{type}</span>
                            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-primary/10 text-primary">{items.length}</span>
                          </div>
                          <div className="flex items-center gap-1.5">
                            {Object.entries(sevCounts).map(([sev, cnt]) => (
                              <span key={sev} className={`text-[9px] font-mono px-1.5 py-0.5 rounded border ${SEVERITY_BADGE[sev] || ""}`}>
                                {sev}:{cnt}
                              </span>
                            ))}
                          </div>
                        </div>
                        {/* Group Items */}
                        <div className="divide-y divide-outline-variant/20 dark:divide-[#ffffff08]">
                          {items.map((finding) => (
                            <div
                              key={finding.id}
                              className="flex items-center gap-2 px-3 py-1.5 hover:bg-surface-container-high dark:hover:bg-[#2A2A35]/50 cursor-pointer transition-all"
                              onClick={() => router.push(`/findings/${finding.id}`)}
                            >
                              <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${finding.severity === "CRITICAL" ? "bg-error" : finding.severity === "HIGH" ? "bg-orange-500" : finding.severity === "MEDIUM" ? "bg-yellow-500" : finding.severity === "LOW" ? "bg-blue-400" : "bg-green-500"}`} />
                              <span className="text-[10px] font-mono text-on-surface truncate flex-1">{finding.endpoint}</span>
                              <span className="text-[9px] font-mono text-on-surface-variant shrink-0">{finding.source_tool}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  });
                })()}
              </div>
            )}
          </motion.div>

          {/* Timeline Section */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-5"
          >
            <div className="flex items-center gap-2 mb-4">
              <Activity size={14} className="text-primary" />
              <h3 className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest font-headline">
                Timeline
              </h3>
            </div>
            {timeline.length === 0 ? (
              <div className="py-8 text-center">
                <p className="text-[11px] font-mono text-on-surface-variant/40 uppercase tracking-widest">
                  No activity recorded yet
                </p>
              </div>
            ) : (
              <div className="space-y-0">
                {timeline.map((event, i) => (
                  <div key={event.id} className="flex gap-3 pb-3 relative">
                    {i < timeline.length - 1 && (
                      <div className="absolute left-[7px] top-4 bottom-0 w-px bg-outline-variant/30" />
                    )}
                    <div className="w-[15px] shrink-0 flex justify-center pt-0.5">
                      <div className={`w-2 h-2 rounded-full border-2 border-primary bg-surface`} />
                    </div>
                    <div className="flex-1 min-w-0 pb-2">
                      <div className="text-xs text-on-surface">{event.message || event.event_type}</div>
                      <div className="text-[9px] font-mono text-on-surface-variant mt-0.5">
                        {new Date(event.created_at).toLocaleString()}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </motion.div>

          {/* Agent Reasoning Feed — shown only in scanning or complete states */}
          {engagement && ["created", "recon", "scanning", "analyzing", "reporting", "complete"].includes(engagement.status) && (
            <AgentReasoningFeed
              decisions={agentDecisions}
              isActive={engagement.status === "scanning"}
            />
          )}

          {/* Explainability — shown only for completed engagements */}
          {engagement && ["complete", "failed"].includes(engagement.status) && (
            <EngagementExplainability engagementId={engagementId} />
          )}
        </div>
      </div>
    </div>
  );
}

// ── Engagement Explainability Component ──

function EngagementExplainability({ engagementId }: { engagementId: string }) {
  const [loading, setLoading] = useState(false);
  const [explanation, setExplanation] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleExplain = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/engagement/${engagementId}/explainability`);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.error || "Failed to generate explanation");
        return;
      }
      const data = await res.json();
      if (data.traces && data.traces.length > 0) {
        // Use the first trace's explanation if available
        setExplanation(data.traces[0].explanation || JSON.stringify(data.traces[0].trace_data, null, 2));
      } else {
        // Fallback: try the AI explain endpoint
        const explainRes = await fetch("/api/ai/explain", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ engagement_id: engagementId }),
        });
        if (explainRes.ok) {
          const explainData = await explainRes.json();
          setExplanation(explainData.explanation || explainData.summary || "Explanation generated.");
        } else {
          setError("AI explanation unavailable. Configure an API key in Settings.");
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate explanation");
    } finally {
      setLoading(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3 }}
      className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-5"
    >
      <div className="flex items-center gap-2 mb-4">
        <Sparkles size={14} className="text-primary" />
        <h3 className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest font-headline">
          AI Explainability
        </h3>
      </div>

      {!explanation && !loading && !error && (
        <div className="py-6 text-center">
          <p className="text-[11px] font-mono text-on-surface-variant/40 uppercase tracking-widest mb-4">
            Get an AI-powered plain-English explanation of this scan&apos;s findings
          </p>
          <button
            onClick={handleExplain}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-primary text-white font-bold text-xs tracking-widest uppercase rounded-lg hover:bg-primary/90 transition-all"
          >
            <Sparkles size={14} />
            Generate Explanation
          </button>
        </div>
      )}

      {loading && (
        <div className="space-y-3 animate-pulse">
          <div className="h-4 bg-surface-container-high rounded w-3/4" />
          <div className="h-4 bg-surface-container-high rounded w-1/2" />
          <div className="h-4 bg-surface-container-high rounded w-5/6" />
        </div>
      )}

      {error && (
        <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-500">
          {error}
        </div>
      )}

      {explanation && !loading && (
        <div className="space-y-3">
          <div className="p-4 rounded-lg bg-surface-container border border-outline-variant/30">
            <p className="text-sm text-on-surface leading-relaxed whitespace-pre-wrap">{explanation}</p>
          </div>
          <button
            onClick={() => setExplanation(null)}
            className="text-[10px] font-mono text-primary hover:text-primary/80 transition-colors"
          >
            Clear & regenerate
          </button>
        </div>
      )}
    </motion.div>
  );
}

// ── Agent Reasoning Feed Component ──

function AgentReasoningFeed({
  decisions,
  isActive,
}: {
  decisions: AgentDecisionEvent[];
  isActive: boolean;
}) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.25 }}
      className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-5"
    >
      <div className="flex items-center gap-2 mb-4">
        <Brain size={14} className="text-primary" />
        <h3 className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest font-headline">
          AI Agent Decisions
        </h3>
        {isActive && (
          <span className="ml-auto flex items-center gap-1.5 text-[9px] font-mono text-primary px-2 py-0.5 rounded-full bg-primary/10 border border-primary/20">
            <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
            Active
          </span>
        )}
      </div>

      {decisions.length === 0 && isActive && (
        <div className="py-8 text-center space-y-3">
          <div className="flex justify-center gap-1">
            <span className="w-2 h-2 rounded-full bg-primary/40 animate-bounce" style={{ animationDelay: "0ms" }} />
            <span className="w-2 h-2 rounded-full bg-primary/40 animate-bounce" style={{ animationDelay: "150ms" }} />
            <span className="w-2 h-2 rounded-full bg-primary/40 animate-bounce" style={{ animationDelay: "300ms" }} />
          </div>
          <p className="text-[11px] font-mono text-on-surface-variant/60 uppercase tracking-widest animate-pulse">
            Waiting for LLM tool selections...
          </p>
        </div>
      )}

      {decisions.length === 0 && !isActive && (
        <div className="py-8 text-center">
          <p className="text-[11px] font-mono text-on-surface-variant/40 uppercase tracking-widest">
            No agent decisions recorded
          </p>
          {!isActive && (
            <p className="text-[9px] font-mono text-on-surface-variant/30 mt-2">
              Agent mode may have been disabled for this engagement
            </p>
          )}
        </div>
      )}

      <AnimatePresence>
        <div className="space-y-2">
          {decisions.map((event, idx) => {
            const isExpanded = expandedIdx === idx;
            const reasoningPreview = event.data.reasoning
              ? event.data.reasoning.length > 150
                ? event.data.reasoning.slice(0, 150) + "..."
                : event.data.reasoning
              : "No reasoning provided";

            return (
              <motion.div
                key={`${event.data.iteration}-${event.data.tool}`}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.05 }}
                className={`flex gap-3 p-3 rounded-lg border transition-all cursor-pointer ${
                  event.data.was_fallback
                    ? "border-outline-variant/30 bg-surface-container/50 hover:bg-surface-container"
                    : "border-primary/20 bg-primary/5 hover:bg-primary/10"
                }`}
                onClick={() => setExpandedIdx(isExpanded ? null : idx)}
              >
                {/* Iteration circle */}
                <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-[10px] font-bold font-mono ${
                  event.data.was_fallback
                    ? "bg-outline-variant/20 text-on-surface-variant"
                    : "bg-primary/20 text-primary"
                }`}>
                  {event.data.iteration + 1}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-mono font-bold text-on-surface">
                      {event.data.tool}
                    </span>
                    <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded-full border ${
                      event.data.was_fallback
                        ? "bg-outline-variant/20 text-on-surface-variant border-outline-variant/30"
                        : "bg-primary/15 text-primary border-primary/30"
                    }`}>
                      {event.data.was_fallback ? "DETERMINISTIC" : "LLM"}
                    </span>
                  </div>
                  <p className="text-[11px] text-on-surface-variant leading-relaxed">
                    {isExpanded ? event.data.reasoning : reasoningPreview}
                  </p>
                  {event.data.reasoning && event.data.reasoning.length > 150 && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setExpandedIdx(isExpanded ? null : idx);
                      }}
                      className="text-[9px] font-mono text-primary hover:text-primary/80 mt-1 transition-colors"
                    >
                      {isExpanded ? "Show less" : "Show more"}
                    </button>
                  )}
                  {/* Timestamp */}
                  <div className="text-[9px] font-mono text-on-surface-variant/40 mt-1">
                    {(() => {
                      const ts = new Date(event.timestamp).getTime();
                      const now = Date.now();
                      const diffSec = Math.floor((now - ts) / 1000);
                      if (diffSec < 5) return "just now";
                      if (diffSec < 60) return `${diffSec}s ago`;
                      const diffMin = Math.floor(diffSec / 60);
                      if (diffMin < 60) return `${diffMin}m ago`;
                      return new Date(event.timestamp).toLocaleTimeString();
                    })()}
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      </AnimatePresence>
    </motion.div>
  );
}
