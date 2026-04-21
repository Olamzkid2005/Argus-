"use client";

import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useEngagementEvents } from "@/lib/use-engagement-events";
import { WebSocketEvent } from "@/lib/websocket-events";
import { useToast } from "@/components/ui/Toast";
import {
  Activity,
  ShieldAlert,
  Globe,
  Clock,
  Zap,
  ChevronRight,
  Radio,
  Target,
  Lock,
  Database,
  RefreshCcw,
  Trash2,
  Cpu,
  CheckCircle2,
  XCircle,
  Loader2,
  Terminal,
} from "lucide-react";
import SurveillanceEye from "@/components/effects/SurveillanceEye";
import MatrixDataRain from "@/components/effects/MatrixDataRain";
import ScannerReveal from "@/components/effects/ScannerReveal";
import SkeletonLoader from "@/components/ui-custom/SkeletonLoader";
import { AIStatusBadge } from "@/components/ui-custom/AIStatus";
import ScannerActivityPanel from "@/components/ui-custom/ScannerActivityPanel";
import { useScannerActivities } from "@/lib/use-scanner-activities";

// ── Components ──

function StatCard({
  label,
  value,
  icon: Icon,
  color,
  index,
}: {
  label: string;
  value: string | number;
  icon: React.ElementType;
  color: string;
  index: number;
}) {
  return (
    <div
      className="relative border border-structural bg-surface/50 p-5 group hover:border-prism-cream/20 transition-all duration-300"
      style={{ animationDelay: `${index * 100}ms` }}
    >
      <div className="flex items-start justify-between mb-4">
        <div
          className="w-9 h-9 flex items-center justify-center border border-structural bg-surface/10"
        >
          {/* @ts-ignore */}
          <Icon size={18} style={{ color }} />
        </div>
        <Zap size={14} className="text-text-secondary opacity-0 group-hover:opacity-100 transition-opacity" />
      </div>
      <div className="text-2xl font-semibold text-text-primary tracking-tight">{value}</div>
      <div className="text-xs text-text-secondary mt-1 tracking-wide uppercase">{label}</div>
    </div>
  );
}

function ThreatFeedRow({ event }: { event: WebSocketEvent }) {
  const [hovered, setHovered] = useState(false);
  
  const getSeverityColor = (severity: string): string => {
    switch (String(severity).toUpperCase()) {
      case "CRITICAL": return "#FF4444";
      case "HIGH": return "#FF8800";
      case "MEDIUM": return "var(--prism-cream)";
      case "LOW": return "var(--prism-cyan)";
      default: return "var(--text-secondary)";
    }
  };

  const severity = (event.data.severity as string) || "Info";
  const color = getSeverityColor(severity);

  return (
    <div
      className="flex items-center gap-4 px-5 py-3 border-b border-structural last:border-b-0 group cursor-pointer hover:bg-surface/10 transition-colors"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className="w-2 h-2 shrink-0" style={{ backgroundColor: color }} />
      <div className="flex-1 min-w-0">
        <div className="text-sm text-text-primary flex items-center gap-2">
          <Radio size={12} className="text-text-secondary" />
          {event.data.finding_type as string || event.type}
        </div>
        <div className="text-[11px] text-text-secondary font-mono mt-0.5 truncate uppercase">
          {event.data.endpoint as string || "System intelligence"}
        </div>
      </div>
      <div className="flex items-center gap-3">
        <span
          className="text-[11px] font-mono px-2 py-0.5 border"
          style={{
            color,
            borderColor: "var(--border-structural)",
            backgroundColor: "transparent",
            boxShadow: hovered ? `0 0 8px ${color}20` : "none",
            transition: "box-shadow 0.3s",
          }}
        >
          {severity}
        </span>
        <span className="text-[11px] text-text-secondary font-mono w-14 text-right">
          {new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </span>
      </div>
    </div>
  );
}

function TimelineRow({ event }: { event: WebSocketEvent }) {
  const statusColor: Record<string, string> = {
    job_started: "var(--prism-cyan)",
    error: "#FF4444",
    job_completed: "#00FF88",
    state_transition: "var(--prism-cream)",
  };

  return (
    <div className="flex items-start gap-4 px-5 py-3 border-b border-structural last:border-b-0">
      <div className="text-[11px] text-text-secondary font-mono w-12 shrink-0 pt-0.5">
        {new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
      </div>
      <div className="w-[6px] h-[6px] mt-1.5 shrink-0" style={{ backgroundColor: statusColor[event.type] || "var(--text-secondary)" }} />
      <div className="flex-1 min-w-0">
        <div className="text-sm text-text-primary capitalize">{event.type.replace(/_/g, " ")}</div>
        <div className="text-[11px] text-text-secondary font-mono mt-0.5 truncate uppercase">
          {event.data.message as string || event.data.from_state as string + " → " + event.data.to_state as string || ""}
        </div>
      </div>
    </div>
  );
}

// ── Main Page ──
export default function DashboardPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data: session, status } = useSession();
  const { showToast } = useToast();
  
  const heroRef = useRef<HTMLDivElement>(null);
  const [eyeOpacity, setEyeOpacity] = useState(1);
  const [engagementId, setEngagementId] = useState<string>("");
  const [isConnected, setIsConnected] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [currentState, setCurrentState] = useState<string>("created");
  const [dbStats, setDbStats] = useState<{
    totalFindings: number;
    totalEngagements: number;
    criticalCount: number;
    verifiedCount: number;
  } | null>(null);
  const [recentEngagements, setRecentEngagements] = useState<any[]>([]);
  const [dbFindings, setDbFindings] = useState<any[]>([]);

  // Persist active engagement to localStorage + URL so it survives navigation
  const connectEngagement = useCallback((id: string) => {
    setEngagementId(id);
    setIsConnected(true);
    localStorage.setItem("argus:active_engagement", id);
    // Sync to URL so back/forward and bookmarks work
    const url = new URL(window.location.href);
    url.searchParams.set("engagement", id);
    window.history.replaceState({}, "", url.toString());
  }, []);

  const disconnectEngagement = useCallback(() => {
    setEngagementId("");
    setIsConnected(false);
    setCurrentState("created");
    localStorage.removeItem("argus:active_engagement");
    const url = new URL(window.location.href);
    url.searchParams.delete("engagement");
    window.history.replaceState({}, "", url.toString());
  }, []);

  // Restore active engagement on mount (from URL or localStorage)
  useEffect(() => {
    const urlId = searchParams.get("engagement");
    if (urlId) {
      setEngagementId(urlId);
      setIsConnected(true);
      return;
    }
    const storedId = localStorage.getItem("argus:active_engagement");
    if (storedId) {
      setEngagementId(storedId);
      setIsConnected(true);
      // Sync back to URL
      const url = new URL(window.location.href);
      url.searchParams.set("engagement", storedId);
      window.history.replaceState({}, "", url.toString());
    }
  }, [searchParams]);

  // Fetch findings from DB so they persist beyond Redis TTL
  useEffect(() => {
    if (!engagementId || !isConnected) return;
    const fetchFindings = async () => {
      try {
        const res = await fetch(`/api/engagement/${engagementId}/findings?limit=50`);
        if (res.ok) {
          const data = await res.json();
          setDbFindings(data.findings || []);
        }
      } catch (e) {
        console.error("Failed to fetch findings:", e);
      }
    };
    fetchFindings();
    const interval = setInterval(fetchFindings, 5000);
    return () => clearInterval(interval);
  }, [engagementId, isConnected]);

  const {
    events,
    currentState: wsCurrentState,
    isConnected: wsConnected,
    reconnect,
    clearEvents,
  } = useEngagementEvents({
    engagementId,
    enabled: isConnected && !!engagementId,
    pollingInterval: 2000,
    onEvent: (event: WebSocketEvent) => {
      if (event.type === "state_transition") {
        setCurrentState(event.data.to_state as string);
      }
    },
    onError: (err: Error) => {
      console.error("WebSocket error:", err);
      showToast("error", "Connection lost");
    },
  });

  // Poll scanner activities from database for persistent live visibility
  const { activities: scannerActivities } = useScannerActivities({
    engagementId: engagementId || null,
    enabled: isConnected && !!engagementId,
    pollingInterval: 2000,
  });

  // Handle scroll for eye effect
  useEffect(() => {
    const handleScroll = () => {
      if (!heroRef.current) return;
      const rect = heroRef.current.getBoundingClientRect();
      const fadeStart = -rect.height * 0.3;
      const fadeEnd = -rect.height * 0.7;
      if (rect.top < fadeStart && rect.top > fadeEnd) {
        const progress = (rect.top - fadeStart) / (fadeEnd - fadeStart);
        setEyeOpacity(Math.max(0.15, progress));
      } else if (rect.top <= fadeEnd) {
        setEyeOpacity(0.15);
      } else {
        setEyeOpacity(1);
      }
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  // Auth redirect
  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/auth/signin");
    }
  }, [status, router]);

  // Engagement selection from URL
  useEffect(() => {
    const urlEngagementId = searchParams.get("engagement");
    if (urlEngagementId) {
      setEngagementId(urlEngagementId);
      setIsConnected(true);
    }
  }, [searchParams]);

  // Fetch real dashboard stats from DB
  useEffect(() => {
    if (status !== "authenticated") return;
    const fetchStats = async () => {
      try {
        const response = await fetch("/api/dashboard/stats");
        if (response.ok) {
          const data = await response.json();
          setDbStats({
            totalFindings: parseInt(data.findings?.total_findings) || 0,
            totalEngagements: parseInt(data.engagements?.total_engagements) || 0,
            criticalCount: parseInt(data.findings?.critical) || 0,
            verifiedCount: parseInt(data.findings?.verified) || 0,
          });
          setRecentEngagements(data.recent_engagements || []);
        }
      } catch (err) {
        console.error("Failed to fetch dashboard stats:", err);
      }
    };
    fetchStats();
  }, [status]);

  // Poll engagement state from DB — Redis TTL can expire, DB is the source of truth
  useEffect(() => {
    if (!engagementId) return;
    const fetchState = async () => {
      try {
        const res = await fetch(`/api/engagement/${engagementId}`);
        if (res.ok) {
          const data = await res.json();
          if (data.engagement?.status) {
            setCurrentState(data.engagement.status);
          }
        }
      } catch (e) {
        console.error("Failed to fetch engagement state:", e);
      }
    };
    fetchState();
    const interval = setInterval(fetchState, 3000);
    return () => clearInterval(interval);
  }, [engagementId]);

  const handleApprove = async () => {
    if (!engagementId || isApproving) return;
    setIsApproving(true);
    try {
      const response = await fetch(`/api/engagement/${engagementId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Failed to approve engagement");
      setCurrentState("scanning");
      showToast("success", "Findings approved! Scan job queued.");
    } catch (err) {
      showToast("error", err instanceof Error ? err.message : "Failed to approve");
    } finally {
      setIsApproving(false);
    }
  };

  const wsFindings = useMemo(() => events.filter(e => e.type === "finding_discovered"), [events]);
  // Merge DB findings (persistent) with WebSocket findings (real-time)
  const findings = useMemo(() => {
    const wsIds = new Set(wsFindings.map((f: any) => f.data?.finding_id));
    const merged = [...wsFindings];
    dbFindings.forEach((df: any) => {
      if (!wsIds.has(df.id)) {
        merged.push({
          type: "finding_discovered",
          engagement_id: engagementId,
          timestamp: df.created_at,
          data: {
            finding_id: df.id,
            finding_type: df.finding_type,
            severity: df.severity,
            confidence: df.confidence,
            endpoint: df.endpoint,
            source_tool: df.source_tool,
          },
        } as WebSocketEvent);
      }
    });
    return merged;
  }, [wsFindings, dbFindings, engagementId]);

  // Timeline shows state transitions, jobs, errors — NOT scanner activities (they have their own panel)
  const otherEvents = useMemo(() => events.filter(e => e.type !== "finding_discovered" && e.type !== "scanner_activity"), [events]);

  const stats = [
    {
      label: "Total Findings",
      value: dbStats?.totalFindings ?? findings.length,
      icon: Activity,
      color: "var(--prism-cyan)",
    },
    {
      label: "Engagements",
      value: dbStats?.totalEngagements ?? 0,
      icon: ShieldAlert,
      color: "var(--prism-cream)",
    },
    {
      label: "Critical Issues",
      value: dbStats?.criticalCount ?? 0,
      icon: Globe,
      color: "#FF4444",
    },
    {
      label: "Verified",
      value: dbStats?.verifiedCount ?? 0,
      icon: Clock,
      color: "#00FF88",
    },
  ];

  if (status === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-void">
        <Loader2 className="h-8 w-8 animate-spin text-prism-cream" />
      </div>
    );
  }

  if (!session) return null;

  return (
    <div className="min-h-screen bg-void">
      {/* ── Surveillance Header ── */}
      <div ref={heroRef} className="relative w-full h-[50vh] overflow-hidden bg-void border-b border-structural">
        <div className="absolute inset-0 z-0 opacity-20">
          <MatrixDataRain />
        </div>

        <div className="absolute inset-0 z-10 flex items-center">
          <div className="pl-12 max-w-lg">
            <div className="flex items-center gap-4 mb-3">
              <div className="flex items-center gap-2">
                <div className={`w-2 h-2 ${wsConnected ? "bg-prism-cream" : "bg-red-500"} animate-pulse`} />
                <span className="text-[11px] font-mono text-text-secondary tracking-widest uppercase">
                  {wsConnected ? "System Online" : "Connection Standby"}
                </span>
              </div>
              <AIStatusBadge />
            </div>
            <h1 className="text-5xl font-semibold text-text-primary tracking-tight leading-[1.1]">
              INTELLIGENCE
              <br />
              DASHBOARD
            </h1>
            
            <div className="mt-8 flex gap-3 max-w-md">
              <div className="relative flex-1">
                <Database className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-text-secondary" />
                <input
                  type="text"
                  placeholder="Engagement ID..."
                  value={engagementId}
                  onChange={(e) => setEngagementId(e.target.value)}
                  className="w-full pl-9 pr-4 py-2.5 bg-surface/50 border border-structural text-xs font-mono outline-none focus:border-prism-cream transition-colors text-text-primary"
                />
              </div>
              <button
                onClick={() => {
                  if (isConnected) {
                    disconnectEngagement();
                  } else {
                    connectEngagement(engagementId);
                  }
                }}
                disabled={!engagementId}
                className={`px-6 py-2 px-6 rounded-sm text-xs font-bold transition-all ${
                  isConnected
                    ? "bg-red-500/10 text-red-500 border border-red-500/20 hover:bg-red-500/20"
                    : "bg-prism-cream text-void hover:opacity-90 shadow-glow-cream"
                } disabled:opacity-50`}
              >
                {isConnected ? "HALT" : "MONITOR"}
              </button>
            </div>
          </div>
        </div>

        <div
          className="absolute top-0 right-0 w-[70%] h-full z-[1] pointer-events-none"
          style={{ opacity: eyeOpacity }}
        >
          <SurveillanceEye />
        </div>
        <div className="absolute bottom-0 left-0 right-0 h-24 bg-gradient-to-t from-void to-transparent z-20" />
      </div>

      {/* ── Main Content ── */}
      <div className="relative z-10 px-8 py-8 -mt-16">
        {/* State Bar */}
        {isConnected && currentState && (
          <div className="border border-structural bg-surface/80 backdrop-blur-md p-4 mb-8 flex items-center justify-between">
            <div className="flex items-center gap-4 ml-4">
              <div className="relative w-8 h-8 flex items-center justify-center">
                <div className="absolute inset-0 border border-prism-cyan/30 rounded-full animate-spin [animation-duration:3s]" />
                <ShieldAlert className="h-4 w-4 text-prism-cyan" />
              </div>
              <span className="text-xs font-bold text-text-secondary uppercase tracking-widest">
                Operational Phase: <span className="text-text-primary">{currentState.replace(/_/g, " ")}</span>
              </span>
            </div>

            <div className="flex gap-3">
              {currentState === "awaiting_approval" && (
                <button
                  onClick={handleApprove}
                  disabled={isApproving}
                  className="px-6 py-2 bg-prism-cream text-void font-bold text-[10px] tracking-widest uppercase hover:bg-white transition-colors disabled:opacity-50 shadow-glow-cream"
                >
                  {isApproving ? "AUTHORIZING..." : "AUTHORIZE EXECUTION"}
                </button>
              )}
              <button onClick={reconnect} className="p-2 text-text-secondary hover:text-text-primary transition-colors">
                <RefreshCcw size={16} />
              </button>
              <button onClick={clearEvents} className="p-2 text-text-secondary hover:text-red-400 transition-colors">
                <Trash2 size={16} />
              </button>
            </div>
          </div>
        )}

        {/* Stats Grid */}
        <div className="grid grid-cols-4 gap-4 mb-8">
          {stats.map((s, i) => <StatCard key={s.label} {...s} index={i} />)}
        </div>

        {/* Two Column Layout */}
        <div className="grid grid-cols-3 gap-6 text-text-primary">
          {/* Threat Feed */}
          <div className="col-span-2 border border-structural bg-surface/30">
            <div className="flex items-center justify-between px-5 py-4 border-b border-structural">
              <div className="flex items-center gap-2">
                <Radio size={16} className="text-prism-cream" />
                <h2 className="text-sm font-medium text-text-primary tracking-wide uppercase">
                  Network Intelligence Feed
                </h2>
              </div>
              <button 
                onClick={() => router.push(`/findings?engagement=${engagementId}`)}
                className="flex items-center gap-1 text-[11px] text-text-secondary hover:text-text-primary transition-colors"
              >
                Deep View <ChevronRight size={12} />
              </button>
            </div>
            <div className="max-h-[600px] overflow-y-auto">
              {!isConnected ? (
                <div className="p-5">
                  {/* System Overview */}
                  <div className="grid grid-cols-3 gap-3 mb-5">
                    <div className="border border-structural bg-surface/20 p-3">
                      <div className="text-[10px] font-mono text-text-secondary uppercase tracking-wider mb-1">Total Findings</div>
                      <div className="text-xl font-semibold text-prism-cyan">{dbStats?.totalFindings ?? 0}</div>
                    </div>
                    <div className="border border-structural bg-surface/20 p-3">
                      <div className="text-[10px] font-mono text-text-secondary uppercase tracking-wider mb-1">Critical</div>
                      <div className="text-xl font-semibold text-red-400">{dbStats?.criticalCount ?? 0}</div>
                    </div>
                    <div className="border border-structural bg-surface/20 p-3">
                      <div className="text-[10px] font-mono text-text-secondary uppercase tracking-wider mb-1">Verified</div>
                      <div className="text-xl font-semibold text-green-400">{dbStats?.verifiedCount ?? 0}</div>
                    </div>
                  </div>

                  {/* Recent Engagements */}
                  <div className="mb-4">
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-[11px] font-bold text-text-secondary uppercase tracking-widest">Recent Engagements</h3>
                      <button 
                        onClick={() => router.push("/engagements")}
                        className="text-[10px] text-prism-cyan hover:underline"
                      >
                        View All
                      </button>
                    </div>
                    {recentEngagements.length === 0 ? (
                      <div className="text-center py-6 text-text-secondary/40 text-xs font-mono uppercase">
                        No engagements yet
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {recentEngagements.slice(0, 5).map((eng) => (
                          <div 
                            key={eng.id} 
                            className="flex items-center justify-between px-3 py-2 border border-structural bg-surface/10 hover:bg-surface/20 transition-colors cursor-pointer"
                            onClick={() => {
                              connectEngagement(eng.id);
                            }}
                          >
                            <div className="flex items-center gap-3">
                              <div className={`w-2 h-2 rounded-full ${
                                eng.status === 'complete' ? 'bg-green-400' :
                                eng.status === 'failed' ? 'bg-red-400' :
                                eng.status === 'scanning' ? 'bg-prism-cyan animate-pulse' :
                                'bg-prism-cream'
                              }`} />
                              <div>
                                <div className="text-xs text-text-primary font-mono truncate max-w-[200px]">{eng.target_url}</div>
                                <div className="text-[10px] text-text-secondary uppercase">{eng.status.replace(/_/g, " ")}</div>
                              </div>
                            </div>
                            <div className="flex items-center gap-3">
                              {eng.findings_count > 0 && (
                                <span className="text-[10px] font-mono text-prism-cream">{eng.findings_count} findings</span>
                              )}
                              <ChevronRight size={12} className="text-text-secondary" />
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Quick Actions */}
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => router.push("/engagements")}
                      className="flex items-center gap-2 px-4 py-2 bg-prism-cream text-void text-xs font-bold uppercase tracking-widest hover:opacity-90 transition-all shadow-glow-cream"
                    >
                      <Target size={14} />
                      New Engagement
                    </button>
                    <button
                      onClick={() => router.push("/findings")}
                      className="flex items-center gap-2 px-4 py-2 border border-structural text-text-secondary hover:text-text-primary hover:border-text-secondary/40 transition-all text-xs uppercase font-bold tracking-widest"
                    >
                      <ShieldAlert size={14} />
                      View Findings
                    </button>
                  </div>
                </div>
              ) : findings.length === 0 ? (
                <div className="p-5">
                  {/* Live scan status */}
                  <div className="flex items-center gap-3 mb-4 pb-4 border-b border-structural">
                    <div className="relative w-8 h-8 flex items-center justify-center">
                      <div className="absolute inset-0 border border-prism-cyan/30 rounded-full animate-spin [animation-duration:3s]" />
                      <Activity className="h-4 w-4 text-prism-cyan" />
                    </div>
                    <div>
                      <p className="text-xs font-bold text-text-primary uppercase tracking-widest">Active Scan In Progress</p>
                      <p className="text-[10px] text-text-secondary font-mono mt-0.5">
                        {scannerActivities.length > 0
                          ? `${scannerActivities.filter((a) => a.status === "completed").length} / ${scannerActivities.length} operations complete`
                          : "Initializing scanner toolkit..."}
                      </p>
                    </div>
                  </div>

                  {/* Scanner steps */}
                  <div className="space-y-1">
                    {scannerActivities.length === 0 ? (
                      <div className="flex items-center gap-3 px-3 py-2 text-text-secondary/40">
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
                            className={`flex items-center gap-3 px-3 py-2 border border-transparent hover:border-structural/40 transition-all ${
                              isDone ? "opacity-60" : isFailed ? "opacity-80" : "bg-prism-cyan/5 border-prism-cyan/10"
                            }`}
                          >
                            {isDone ? (
                              <CheckCircle2 size={12} className="text-green-400 shrink-0" />
                            ) : isFailed ? (
                              <XCircle size={12} className="text-red-400 shrink-0" />
                            ) : (
                              <Loader2 size={12} className="text-prism-cyan animate-spin shrink-0" />
                            )}
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="text-[10px] font-bold font-mono uppercase text-text-secondary">
                                  {activity.tool_name}
                                </span>
                                {activity.items_found !== null && activity.items_found !== undefined && (
                                  <span className="text-[10px] font-mono text-prism-cream">
                                    {activity.items_found} found
                                  </span>
                                )}
                              </div>
                              <p className="text-[11px] text-text-primary truncate">{activity.activity}</p>
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              ) : (
                findings.map((event, i) => <ThreatFeedRow key={i} event={event} />)
              )}
            </div>
          </div>

          {/* Right Column */}
          <div className="flex flex-col gap-6">
            {/* Live Scanner Activity */}
            <div className="border border-structural bg-surface/30">
              <div className="flex items-center gap-2 px-5 py-4 border-b border-structural">
                <Terminal size={16} className="text-prism-cream" />
                <h2 className="text-sm font-medium text-text-primary tracking-wide uppercase">Live Operations</h2>
                {isConnected && scannerActivities.some((a) => a.status === "started" || a.status === "in_progress") && (
                  <div className="ml-auto flex items-center gap-1.5">
                    <span className="relative flex h-2 w-2">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-prism-cyan opacity-75" />
                      <span className="relative inline-flex rounded-full h-2 w-2 bg-prism-cyan" />
                    </span>
                    <span className="text-[10px] font-mono text-prism-cyan uppercase">LIVE</span>
                  </div>
                )}
              </div>
              <ScannerActivityPanel activities={scannerActivities} />
            </div>

            {/* Timeline */}
            <div className="border border-structural bg-surface/30">
              <div className="flex items-center gap-2 px-5 py-4 border-b border-structural">
                <Clock size={16} className="text-prism-cyan" />
                <h2 className="text-sm font-medium text-text-primary tracking-wide uppercase">Timeline</h2>
              </div>
              <div className="max-h-[400px] overflow-y-auto">
                {otherEvents.map((event, i) => (
                  <TimelineRow key={i} event={event} />
                ))}
              </div>
            </div>

            {/* Verification Status */}
            <div className="border border-structural bg-surface/30 p-5">
              <h3 className="text-xs font-medium text-text-secondary tracking-widest uppercase mb-4">Security Integrity</h3>
              <div className="space-y-3">
                <ScannerReveal
                  icon="/assets/holographic-lock.png"
                  text={wsConnected ? "VERIFIED" : "STANDBY"}
                  scannedText="ENCRYPTED"
                  className="w-full h-16 border-structural bg-surface/10"
                  glowColor="var(--prism-cream)"
                />
                <ScannerReveal
                  icon="/assets/prism-verified.png"
                  text={isConnected ? "MONITORING" : "OFFLINE"}
                  scannedText="PROTECTED"
                  className="w-full h-16 border-structural bg-surface/10"
                  glowColor="var(--prism-cyan)"
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
