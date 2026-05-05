"use client";

import { useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Radio,
  ChevronRight,
  Loader2,
  CheckCircle2,
  XCircle,
  Activity,
  Eye,
  StopCircle,
  Trash2,
  Target,
  ShieldAlert,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { WebSocketEvent } from "@/lib/websocket-events";

interface FindingsPanelProps {
  isConnected: boolean;
  findings: any[];
  dbStats: any;
  recentEngagements: any[];
  scannerActivities: any[];
  currentState: string;
  scanStartTime: string | null;
  engagementId: string;
  stoppingId: string | null;
  deletingId: string | null;
  rescannings: Set<string>;
  getScanProgress: (status: string) => number;
  handleStop: (id: string) => void;
  handleDelete: (id: string) => void;
  handleRescan: (id: string) => void;
  connectEngagement: (id: string) => void;
}

function ThreatFeedRow({ event }: { event: WebSocketEvent }) {
  const [hovered, setHovered] = useState(false);

  const getSeverityColor = (severity: string): string => {
    switch (String(severity).toUpperCase()) {
      case "CRITICAL": return "#BA1A1A";
      case "HIGH": return "#FF8800";
      case "MEDIUM": return "#6720FF";
      case "LOW": return "#10B981";
      default: return "#7A7489";
    }
  };

  const severity = (event.data.severity as string) || "Info";
  const color = getSeverityColor(severity);

  return (
    <div
      className="flex items-center gap-4 px-5 py-3 border-b border-outline-variant dark:border-[#ffffff08] last:border-b-0 group cursor-pointer hover:bg-surface-container dark:hover:bg-[#1A1A24] transition-all duration-300"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className="w-2 h-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-body text-on-surface dark:text-[#F0F0F5] flex items-center gap-2">
          <Radio size={12} className="text-on-surface-variant dark:text-[#8A8A9E]" />
          {event.data.finding_type as string || event.type}
        </div>
        <div className="text-[11px] text-on-surface-variant dark:text-[#8A8A9E] font-mono mt-0.5 truncate uppercase">
          {event.data.endpoint as string || "System intelligence"}
        </div>
      </div>
      <div className="flex items-center gap-3">
        <span
          className="text-[11px] font-mono px-2 py-0.5 border rounded-md transition-all duration-300"
          style={{
            color,
            borderColor: hovered ? color : "var(--outline-variant)",
            backgroundColor: hovered ? `${color}10` : "transparent",
          }}
        >
          {severity}
        </span>
        <span className="text-[11px] text-on-surface-variant dark:text-[#8A8A9E] font-mono w-14 text-right">
          {new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </span>
      </div>
    </div>
  );
}

export default function FindingsPanel({
  isConnected,
  findings,
  dbStats,
  recentEngagements,
  scannerActivities,
  currentState,
  scanStartTime,
  engagementId,
  stoppingId,
  deletingId,
  rescannings,
  getScanProgress,
  handleStop,
  handleDelete,
  handleRescan,
  connectEngagement,
}: FindingsPanelProps) {
  const router = useRouter();

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.2 }}
      className="col-span-12 lg:col-span-8 bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl overflow-hidden transition-all duration-300 hover:border-primary/20"
    >
      <div className="flex items-center justify-between px-5 py-4 border-b border-outline-variant dark:border-[#ffffff08]">
        <div className="flex items-center gap-2">
          <Radio size={16} className="text-primary" />
          <h2 className="text-sm font-headline font-medium text-on-surface dark:text-[#F0F0F5] tracking-wide uppercase">
            Network Intelligence Feed
          </h2>
          {scanStartTime && (
            <span className="text-[10px] font-mono px-2 py-0.5 bg-primary/10 text-primary border border-primary/20 rounded-md">
              Active Scan Only
            </span>
          )}
        </div>
        <button
          onClick={() => router.push(`/findings?engagement=${engagementId}`)}
          className="flex items-center gap-1 text-[11px] text-on-surface-variant dark:text-[#8A8A9E] hover:text-primary transition-all duration-300"
        >
          Deep View <ChevronRight size={12} />
        </button>
      </div>
      <div className="max-h-[600px] overflow-y-auto">
        <AnimatePresence mode="wait">
          {!isConnected ? (
            <motion.div
              key="overview"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.3 }}
              className="p-5"
            >
              <div className="grid grid-cols-3 gap-3 mb-5">
              <div className="bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08] rounded-lg p-3 transition-all duration-300">
                <div className="text-[10px] font-mono text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider mb-1">Total Findings</div>
                <div className="text-xl font-headline font-semibold text-primary">{dbStats?.totalFindings ?? 0}</div>
              </div>
              <div className="bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08] rounded-lg p-3 transition-all duration-300">
                <div className="text-[10px] font-mono text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider mb-1">Critical</div>
                <div className="text-xl font-headline font-semibold text-error">{dbStats?.criticalCount ?? 0}</div>
              </div>
              <div className="bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08] rounded-lg p-3 transition-all duration-300">
                <div className="text-[10px] font-mono text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider mb-1">Verified</div>
                <div className="text-xl font-headline font-semibold text-green-500">{dbStats?.verifiedCount ?? 0}</div>
              </div>
            </div>

              <div className="mb-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-[11px] font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-widest font-body">Recent Engagements</h3>
                  <button
                    onClick={() => router.push("/engagements")}
                    className="text-[10px] text-primary hover:underline transition-all duration-300"
                  >
                    View All
                  </button>
                </div>
                {recentEngagements.filter((eng) => eng.status !== "complete" && !["complete", "failed"].includes(eng.status)).length === 0 && recentEngagements.filter((eng) => ["complete", "failed"].includes(eng.status)).length === 0 ? (
                  <div className="text-center py-6 text-on-surface-variant/40 dark:text-[#8A8A9E]/40 text-xs font-mono uppercase">
                    No engagements yet
                  </div>
                ) : (
                  <div className="space-y-2">
                    {recentEngagements.filter((eng) => !["complete", "failed"].includes(eng.status)).slice(0, 5).map((eng) => {
                      const progress = getScanProgress(eng.status);
                      const isStopping = stoppingId === eng.id;
                      return (
                        <div
                          key={eng.id}
                          className="px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08] rounded-lg hover:bg-surface-container-high dark:hover:bg-[#1A1A24] transition-all duration-300"
                        >
                          <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-3 flex-1 min-w-0">
                              <div className={`w-2 h-2 rounded-full shrink-0 ${
                                eng.status === 'complete' ? 'bg-green-500' :
                                eng.status === 'failed' ? 'bg-error' :
                                eng.status === 'scanning' || eng.status === 'recon' ? 'bg-primary animate-pulse' :
                                'bg-amber-400'
                              }`} />
                              <div className="min-w-0 flex-1">
                                <div className="text-xs text-on-surface dark:text-[#F0F0F5] font-mono truncate">{eng.target_url}</div>
                                <div className="text-[10px] text-on-surface-variant dark:text-[#8A8A9E] uppercase">{eng.status.replace(/_/g, " ")} • {progress}%</div>
                              </div>
                            </div>
                            <div className="flex gap-1 ml-2">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleStop(eng.id);
                                }}
                                disabled={isStopping}
                                aria-label="Stop scan"
                                className="p-1.5 hover:bg-error/10 rounded text-error transition-all duration-300"
                                title="Stop scan"
                              >
                                {isStopping ? (
                                  <Loader2 size={14} className="animate-spin" />
                                ) : (
                                  <StopCircle size={14} />
                                )}
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  connectEngagement(eng.id);
                                }}
                                aria-label="Monitor"
                                className="p-1.5 hover:bg-primary/10 rounded text-primary transition-all duration-300"
                                title="Monitor"
                              >
                                <Eye size={14} />
                              </button>
                            </div>
                          </div>
                          <div className="h-1 w-full bg-surface-container-high dark:bg-[#1A1A24] rounded-full overflow-hidden">
                            <motion.div
                              className="h-full bg-primary rounded-full"
                              initial={{ width: 0 }}
                              animate={{ width: `${progress}%` }}
                              transition={{ duration: 0.6, ease: "easeOut" }}
                            />
                          </div>
                        </div>
                      );
                    })}
                    {recentEngagements.filter((eng) => ["complete", "failed"].includes(eng.status)).slice(0, 3).map((eng) => {
                      const isDeleting = deletingId === eng.id;
                      return (
                        <div
                          key={eng.id}
                          className="px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08] rounded-lg hover:bg-surface-container-high dark:hover:bg-[#1A1A24] transition-all duration-300"
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-3 flex-1 min-w-0">
                              <div className={`w-2 h-2 rounded-full shrink-0 ${
                                eng.status === 'complete' ? 'bg-green-500' : 'bg-error'
                              }`} />
                              <div className="min-w-0 flex-1">
                                <div className="text-xs text-on-surface dark:text-[#F0F0F5] font-mono truncate">{eng.target_url}</div>
                                <div className="text-[10px] text-on-surface-variant dark:text-[#8A8A9E] uppercase">{eng.status.replace(/_/g, " ")}</div>
                              </div>
                            </div>
                            <div className="flex gap-1 ml-2">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleRescan(eng.id);
                                }}
                                disabled={rescannings.has(eng.id)}
                                aria-label="Rescan"
                                className="p-1.5 hover:bg-primary/10 rounded text-primary transition-all duration-300"
                                title="Rescan"
                              >
                                {rescannings.has(eng.id) ? (
                                  <Loader2 size={14} className="animate-spin" />
                                ) : (
                                  <Loader2 size={14} />
                                )}
                              </button>
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.preventDefault();
                                  e.stopPropagation();
                                  handleDelete(eng.id);
                                }}
                                disabled={isDeleting}
                                aria-label="Delete"
                                className="p-1.5 hover:bg-red-500/10 rounded text-red-400 transition-all duration-300"
                                title="Delete"
                              >
                                {isDeleting ? (
                                  <Loader2 size={14} className="animate-spin" />
                                ) : (
                                  <Trash2 size={14} />
                                )}
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  router.push(`/dashboard?engagement=${eng.id}`);
                                }}
                                aria-label="View"
                                className="p-1.5 hover:bg-primary/10 rounded text-primary transition-all duration-300"
                                title="View"
                              >
                                <Eye size={14} />
                              </button>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={() => router.push("/engagements")}
                  className="flex items-center gap-2 px-4 py-2 bg-primary text-on-primary text-xs font-bold uppercase tracking-widest hover:opacity-90 transition-all duration-300 shadow-glow rounded-lg"
                >
                  <Target size={14} />
                  New Engagement
                </button>
                <button
                  onClick={() => router.push("/findings")}
                  data-tour="findings"
                  className="flex items-center gap-2 px-4 py-2 border border-outline-variant dark:border-[#ffffff10] text-on-surface-variant dark:text-[#8A8A9E] hover:text-on-surface dark:hover:text-[#F0F0F5] hover:border-primary/30 transition-all duration-300 text-xs uppercase font-bold tracking-widest rounded-lg"
                >
                  <ShieldAlert size={14} />
                  View Findings
                </button>
              </div>
            </motion.div>
          ) : findings.length === 0 ? (
            <motion.div
              key="scanning"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.3 }}
              className="p-5"
            >
              <div className="flex items-center gap-3 mb-4 pb-4 border-b border-outline-variant dark:border-[#ffffff08]">
                <div className="relative w-8 h-8 flex items-center justify-center">
                  <div className="absolute inset-0 border border-primary/30 rounded-full animate-spin [animation-duration:3s]" />
                  <Activity className="h-4 w-4 text-primary" />
                </div>
                <div>
                  <p className="text-xs font-bold text-on-surface dark:text-[#F0F0F5] uppercase tracking-widest font-body">Active Scan In Progress</p>
                  <p className="text-[10px] text-on-surface-variant dark:text-[#8A8A9E] font-mono mt-0.5">
                    {scannerActivities.length > 0
                      ? `${scannerActivities.filter((a) => a.status === "completed").length} / ${scannerActivities.length} operations complete`
                      : "Initializing scanner toolkit..."}
                  </p>
                </div>
              </div>

              <div className="space-y-1">
                {scannerActivities.length === 0 ? (
                  <div className="flex items-center gap-3 px-3 py-2 text-on-surface-variant/40 dark:text-[#8A8A9E]/40">
                    {currentState === "scanning" || currentState === "recon" ? (
                      <>
                        <Loader2 size={12} className="animate-spin" />
                        <span className="text-[11px] font-mono">Initializing scanner toolkit...</span>
                      </>
                    ) : (
                      <>
                        <Activity size={12} />
                        <span className="text-[11px] font-mono">Scanner activity not recorded for this engagement</span>
                      </>
                    )}
                  </div>
                ) : (
                  scannerActivities.slice(0, 12).map((activity) => {
                    const isDone = activity.status === "completed";
                    const isFailed = activity.status === "failed";
                    return (
                      <div
                        key={activity.id}
                        className={`flex items-center gap-3 px-3 py-2 rounded-lg border transition-all duration-300 ${
                          isDone ? "opacity-60 border-transparent" : isFailed ? "opacity-80 border-transparent" : "bg-primary/5 border-primary/10"
                        }`}
                      >
                        {isDone ? (
                          <CheckCircle2 size={12} className="text-green-500 shrink-0" />
                        ) : isFailed ? (
                          <XCircle size={12} className="text-error shrink-0" />
                        ) : (
                          <Loader2 size={12} className="text-primary animate-spin shrink-0" />
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-[10px] font-bold font-mono uppercase text-on-surface-variant dark:text-[#8A8A9E]">
                              {activity.tool_name}
                            </span>
                            {activity.items_found !== null && activity.items_found !== undefined && (
                              <span className="text-[10px] font-mono text-primary">
                                {activity.items_found} found
                              </span>
                            )}
                          </div>
                          <p className="text-[11px] text-on-surface dark:text-[#F0F0F5] truncate">{activity.activity}</p>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="feed"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3 }}
              className="divide-y divide-outline-variant dark:divide-[#ffffff08]"
            >
              {findings.map((event, i) => <ThreatFeedRow key={event.id || `finding-${i}`} event={event} />)}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
