"use client";

import { useEffect, useRef, useState, useMemo, useCallback, Suspense, lazy } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useEngagementEvents } from "@/lib/use-engagement-events";
import { WebSocketEvent } from "@/lib/websocket-events";
import { useToast } from "@/components/ui/Toast";
import { motion, AnimatePresence } from "framer-motion";
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
  GitBranch,
  BarChart3,
} from "lucide-react";
import ScannerReveal from "@/components/effects/ScannerReveal";
import SkeletonLoader from "@/components/ui-custom/SkeletonLoader";
import { AIStatusBadge } from "@/components/ui-custom/AIStatus";
import ScannerActivityPanel from "@/components/ui-custom/ScannerActivityPanel";
import { useScannerActivities } from "@/lib/use-scanner-activities";
import { ScrollReveal } from "@/components/animations/ScrollReveal";
import { StaggerContainer, StaggerItem } from "@/components/animations/StaggerContainer";
import { AnimatedCounter } from "@/components/animations/AnimatedCounter";

// Lazy load heavy visualization components
const AttackPathGraph = lazy(() => import("@/components/ui-custom/AttackPathGraph"));
const ExecutionTimeline = lazy(() => import("@/components/ui-custom/ExecutionTimeline"));
const ToolPerformanceMetrics = lazy(() => import("@/components/ui-custom/ToolPerformanceMetrics"));

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
  const numericValue = typeof value === "number" ? value : parseInt(String(value), 10);
  const isNumeric = !isNaN(numericValue);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: index * 0.1 }}
      whileHover={{ y: -2, transition: { duration: 0.25 } }}
      className="relative bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-5 overflow-hidden transition-all duration-300 hover:shadow-glow hover:border-primary/30 group"
      style={{ borderLeftWidth: 4, borderLeftColor: color }}
    >
      <div className="flex items-start justify-between mb-3">
        <div className="w-10 h-10 rounded-lg bg-surface-container dark:bg-[#1A1A24] flex items-center justify-center transition-colors duration-300">
          {/* @ts-ignore */}
          <Icon size={20} style={{ color }} />
        </div>
        <Zap size={14} className="text-on-surface-variant dark:text-[#8A8A9E] opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
      </div>
      <div className="text-3xl font-headline font-bold text-on-surface dark:text-[#F0F0F5] tracking-tight">
        {isNumeric ? <AnimatedCounter value={numericValue} /> : value}
      </div>
      <div className="text-xs font-body text-on-surface-variant dark:text-[#8A8A9E] mt-1 tracking-wide uppercase">{label}</div>
    </motion.div>
  );
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

function TimelineRow({ event }: { event: WebSocketEvent }) {
  const statusColor: Record<string, string> = {
    job_started: "#6720FF",
    error: "#BA1A1A",
    job_completed: "#10B981",
    state_transition: "#FF8800",
  };

  return (
    <div className="flex items-start gap-4 px-5 py-3 border-b border-outline-variant dark:border-[#ffffff08] last:border-b-0 transition-all duration-300 hover:bg-surface-container dark:hover:bg-[#1A1A24]">
      <div className="text-[11px] text-on-surface-variant dark:text-[#8A8A9E] font-mono w-12 shrink-0 pt-0.5">
        {new Date(event.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
      </div>
      <div className="w-[6px] h-[6px] mt-1.5 shrink-0 rounded-full" style={{ backgroundColor: statusColor[event.type] || "#7A7489" }} />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-body text-on-surface dark:text-[#F0F0F5] capitalize">{event.type.replace(/_/g, " ")}</div>
        <div className="text-[11px] text-on-surface-variant dark:text-[#8A8A9E] font-mono mt-0.5 truncate uppercase">
          {event.data.message as string || event.data.from_state as string + " → " + event.data.to_state as string || ""}
        </div>
      </div>
    </div>
  );
}

function ScanStepTimeline({ currentState, activities }: { currentState: string; activities: any[] }) {
  const steps = [
    { id: "recon", label: "Reconnaissance" },
    { id: "fingerprinting", label: "Fingerprinting" },
    { id: "vuln_mapping", label: "Vulnerability Mapping" },
    { id: "reporting", label: "Final Reporting" },
  ];

  const getStepStatus = (stepId: string) => {
    const stateOrder = ["created", "recon", "awaiting_approval", "scanning", "analyzing", "reporting", "complete"];
    const currentIdx = stateOrder.indexOf(currentState);

    if (stepId === "recon") {
      if (currentState === "recon" || currentState === "awaiting_approval") return "in_progress";
      if (currentIdx > stateOrder.indexOf("awaiting_approval")) return "completed";
    }
    if (stepId === "fingerprinting") {
      if (currentState === "scanning") return "in_progress";
      if (currentIdx > stateOrder.indexOf("scanning")) return "completed";
    }
    if (stepId === "vuln_mapping") {
      if (currentState === "analyzing") return "in_progress";
      if (currentIdx > stateOrder.indexOf("analyzing")) return "completed";
    }
    if (stepId === "reporting") {
      if (currentState === "reporting") return "in_progress";
      if (currentState === "complete") return "completed";
    }
    return "pending";
  };

  const completedCount = steps.filter((s) => getStepStatus(s.id) === "completed").length;
  const inProgressCount = steps.filter((s) => getStepStatus(s.id) === "in_progress").length;
  const progress = steps.length > 0 ? ((completedCount + (inProgressCount * 0.5)) / steps.length) * 100 : 0;

  const activeActivity = activities.find((a) => a.status === "started" || a.status === "in_progress");

  return (
    <div className="space-y-5">
      <div className="h-2 w-full bg-surface-container dark:bg-[#1A1A24] rounded-full overflow-hidden">
        <motion.div
          className="h-full bg-primary rounded-full"
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
      </div>

      <div className="space-y-3">
        {steps.map((step, i) => {
          const status = getStepStatus(step.id);
          return (
            <div key={step.id} className="flex items-center gap-3">
              <div
                className={`w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold transition-all duration-300 ${
                  status === "completed"
                    ? "bg-primary text-on-primary"
                    : status === "in_progress"
                    ? "bg-primary/10 text-primary border border-primary"
                    : "bg-surface-container dark:bg-[#1A1A24] text-on-surface-variant dark:text-[#8A8A9E]"
                }`}
              >
                {status === "completed" ? <CheckCircle2 size={14} /> : i + 1}
              </div>
              <span
                className={`text-sm font-body transition-colors duration-300 ${
                  status === "completed"
                    ? "text-on-surface dark:text-[#F0F0F5]"
                    : status === "in_progress"
                    ? "text-primary font-medium"
                    : "text-on-surface-variant dark:text-[#8A8A9E]"
                }`}
              >
                {step.label}
              </span>
              {status === "in_progress" && (
                <Loader2 size={14} className="text-primary animate-spin ml-auto" />
              )}
              {status === "completed" && (
                <CheckCircle2 size={14} className="text-primary ml-auto" />
              )}
            </div>
          );
        })}
      </div>

      {activeActivity && (
        <div className="pt-3 border-t border-outline-variant dark:border-[#ffffff08]">
          <div className="text-[10px] font-mono text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider mb-1.5">
            Current Operation
          </div>
          <div className="flex items-center gap-2">
            <Loader2 size={12} className="text-primary animate-spin shrink-0" />
            <span className="text-xs font-body text-on-surface dark:text-[#F0F0F5] truncate">
              {activeActivity.tool_name}: {activeActivity.activity}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main Page ──
export default function DashboardPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data: session, status } = useSession();
  const { showToast } = useToast();

  const [engagementId, setEngagementId] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    const urlId = new URL(window.location.href).searchParams.get("engagement");
    return urlId || localStorage.getItem("argus:active_engagement") || "";
  });
  const [isConnected, setIsConnected] = useState(() => {
    if (typeof window === "undefined") return false;
    const urlId = new URL(window.location.href).searchParams.get("engagement");
    return !!(urlId || localStorage.getItem("argus:active_engagement"));
  });
  const [isApproving, setIsApproving] = useState(false);
  const [currentState, setCurrentState] = useState<string>(() => {
    if (typeof window === "undefined") return "created";
    const storedState = localStorage.getItem("argus:active_state");
    return storedState || "created";
  });
  const [dbStats, setDbStats] = useState<{
    totalFindings: number;
    totalEngagements: number;
    criticalCount: number;
    verifiedCount: number;
  } | null>(null);
  const [recentEngagements, setRecentEngagements] = useState<any[]>([]);
  const [dbFindings, setDbFindings] = useState<any[]>([]);
  const [toolMetrics, setToolMetrics] = useState<any[]>([]);
  const [timelineEvents, setTimelineEvents] = useState<any[]>([]);
  const [attackPaths, setAttackPaths] = useState<{ nodes: any[]; edges: any[] }>({ nodes: [], edges: [] });
  const accessDeniedNotifiedRef = useRef(false);
  const [engagementStart, setEngagementStart] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    return new Date().toISOString();
  });

  // Persist active engagement to localStorage + URL so it survives navigation
  const connectEngagement = useCallback((id: string) => {
    setEngagementId(id);
    setIsConnected(true);
    accessDeniedNotifiedRef.current = false;
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
    accessDeniedNotifiedRef.current = false;
    localStorage.removeItem("argus:active_engagement");
    localStorage.removeItem("argus:active_state");
    const url = new URL(window.location.href);
    url.searchParams.delete("engagement");
    window.history.replaceState({}, "", url.toString());
  }, []);

  const handleEngagementAccessDenied = useCallback(
    (statusCode: number) => {
      if (statusCode !== 401 && statusCode !== 403) return false;
      if (!accessDeniedNotifiedRef.current) {
        accessDeniedNotifiedRef.current = true;
        showToast("error", "Access to this engagement was denied. Cleared stale selection.");
      }
      disconnectEngagement();
      return true;
    },
    [disconnectEngagement, showToast],
  );

  // Sync URL query param into state when it changes (back/forward navigation)
  useEffect(() => {
    const urlId = searchParams.get("engagement");
    if (urlId && urlId !== engagementId) {
      setEngagementId(urlId);
      setIsConnected(true);
    } else if (!urlId && engagementId && !localStorage.getItem("argus:active_engagement")) {
      // URL cleared and localStorage cleared — disconnect
      setEngagementId("");
      setIsConnected(false);
    }
  }, [searchParams, engagementId]);

  // Persist current state to localStorage whenever it changes
  useEffect(() => {
    if (isConnected && currentState) {
      localStorage.setItem("argus:active_state", currentState);
    }
  }, [currentState, isConnected]);

  // Persist active engagement whenever connected so navigation away/back
  // does not clear the live scan context in the dashboard.
  useEffect(() => {
    if (isConnected && engagementId) {
      localStorage.setItem("argus:active_engagement", engagementId);
    }
  }, [engagementId, isConnected]);

  // Fetch findings from DB so they persist beyond Redis TTL
  useEffect(() => {
    if (!engagementId || !isConnected) return;
    const fetchFindings = async () => {
      try {
        const res = await fetch(`/api/engagement/${engagementId}/findings?limit=50`);
        if (handleEngagementAccessDenied(res.status)) return;
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

  // Auth redirect
  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/auth/signin");
    }
  }, [status, router]);

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

  // Fetch tool performance metrics
  useEffect(() => {
    if (status !== "authenticated") return;
    const fetchMetrics = async () => {
      try {
        const response = await fetch("/api/tools/performance?days=7");
        if (response.ok) {
          const data = await response.json();
          setToolMetrics(data.tools || []);
        }
      } catch (err) {
        console.error("Failed to fetch tool metrics:", err);
      }
    };
    fetchMetrics();
  }, [status]);

  // Fetch execution timeline for active engagement
  useEffect(() => {
    if (!engagementId || !isConnected) {
      setTimelineEvents([]);
      return;
    }
    const fetchTimeline = async () => {
      try {
        const [timelineRes, engagementRes] = await Promise.all([
          fetch(`/api/engagement/${engagementId}/timeline?limit=100`),
          fetch(`/api/engagement/${engagementId}`),
        ]);
        if (
          handleEngagementAccessDenied(timelineRes.status) ||
          handleEngagementAccessDenied(engagementRes.status)
        ) {
          return;
        }
        if (timelineRes.ok) {
          const data = await timelineRes.json();
          const spans = (data.spans || []).map((s: any) => ({
            id: s.id,
            name: s.span_name,
            status: s.duration_ms > 0 ? "completed" : "running",
            startTime: s.created_at,
            endTime: s.duration_ms > 0 ? new Date(new Date(s.created_at).getTime() + s.duration_ms).toISOString() : undefined,
            durationMs: s.duration_ms,
          }));
          setTimelineEvents(spans);
        }
        if (engagementRes.ok) {
          const data = await engagementRes.json();
          if (data.engagement?.created_at) {
            setEngagementStart(data.engagement.created_at);
          }
        }
      } catch (err) {
        console.error("Failed to fetch timeline:", err);
      }
    };
    fetchTimeline();
    const interval = setInterval(fetchTimeline, 10000);
    return () => clearInterval(interval);
  }, [engagementId, isConnected]);

  // Fetch attack paths for active engagement
  useEffect(() => {
    if (!engagementId || !isConnected) {
      setAttackPaths({ nodes: [], edges: [] });
      return;
    }
    const fetchPaths = async () => {
      try {
        const response = await fetch(`/api/engagement/${engagementId}/findings?limit=20`);
        if (handleEngagementAccessDenied(response.status)) return;
        if (response.ok) {
          const data = await response.json();
          const findings = data.findings || [];
          const sortedFindings = [...findings]
            .sort((a: any, b: any) => (Number(b.cvss_score || 0) - Number(a.cvss_score || 0)))
            .slice(0, 4);

          const firstFinding = sortedFindings[0];
          const entryLabel = firstFinding?.endpoint || firstFinding?.target || firstFinding?.host || "External Surface";
          const targetLabel = sortedFindings[sortedFindings.length - 1]?.endpoint || "Critical Asset";

          const nodes = [
            {
              id: "node-entry",
              type: "entry",
              label: "Entry Point",
              description: entryLabel,
              cvss: null,
              confidence: null,
            },
            ...sortedFindings.map((f: any, i: number) => ({
              id: `node-exploit-${i}`,
              type: "exploit",
              label: f.finding_type || f.type || f.title || "Exploit Step",
              description: f.endpoint || f.target || f.source_tool || "Unknown target",
              cvss: f.cvss_score,
              confidence: f.confidence,
            })),
            {
              id: "node-target",
              type: "target",
              label: "Target",
              description: targetLabel,
              cvss: null,
              confidence: null,
            },
          ];

          const edges = nodes.slice(0, -1).map((node: any, i: number) => ({
            source: node.id,
            target: nodes[i + 1].id,
            label: i === 0 ? "recon" : i === nodes.length - 2 ? "impact" : "exploit",
          }));
          setAttackPaths({ nodes, edges });
        }
      } catch (err) {
        console.error("Failed to fetch attack paths:", err);
      }
    };
    fetchPaths();
  }, [engagementId, isConnected]);

  // Poll engagement state from DB — Redis TTL can expire, DB is the source of truth
  useEffect(() => {
    if (!engagementId) return;
    const fetchState = async () => {
      try {
        const res = await fetch(`/api/engagement/${engagementId}`);
        if (handleEngagementAccessDenied(res.status)) return;
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
      color: "#6720FF",
    },
    {
      label: "Engagements",
      value: dbStats?.totalEngagements ?? 0,
      icon: ShieldAlert,
      color: "#A78BFA",
    },
    {
      label: "Critical Issues",
      value: dbStats?.criticalCount ?? 0,
      icon: Globe,
      color: "#BA1A1A",
    },
    {
      label: "Verified",
      value: dbStats?.verifiedCount ?? 0,
      icon: Clock,
      color: "#10B981",
    },
  ];

  if (status === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface matrix-grid">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!session) return null;

  return (
    <div className="min-h-screen bg-surface matrix-grid">
      <div className="max-w-[1440px] mx-auto px-4 sm:px-6 py-8">
        {/* ── Header ── */}
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mb-8"
        >
          <div className="flex items-center gap-3 mb-2">
            <motion.div
              className={`w-2 h-2 rounded-full ${wsConnected ? "bg-primary" : "bg-error"}`}
              animate={{ scale: [1, 1.4, 1], opacity: [1, 0.7, 1] }}
              transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
            />
            <span className="text-xs font-body text-on-surface-variant dark:text-[#8A8A9E] tracking-widest uppercase">
              {wsConnected ? "System Online" : "Connection Standby"}
            </span>
            <AIStatusBadge />
          </div>
          <h1 className="text-4xl font-headline font-semibold text-on-surface dark:text-[#F0F0F5] tracking-tight">
            Main Intelligence Hub
          </h1>
          <p className="text-sm font-body text-on-surface-variant dark:text-[#8A8A9E] mt-1">
            Real-time security monitoring, threat intelligence, and operational command
          </p>
        </motion.div>

        {/* ── Engagement Connection Bar ── */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.1 }}
          className="flex flex-col sm:flex-row items-stretch sm:items-center gap-4 mb-8 p-4 bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl transition-all duration-300"
        >
          <div className="relative flex-1">
            <Database className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-on-surface-variant dark:text-[#8A8A9E]" />
            <input
              type="text"
              placeholder="Engagement ID..."
              value={engagementId}
              onChange={(e) => setEngagementId(e.target.value)}
              className="w-full pl-10 pr-4 py-2.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] rounded-lg text-sm font-mono text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary transition-all duration-300 placeholder:text-on-surface-variant/40 dark:placeholder:text-[#8A8A9E]/40"
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
            className={`px-6 py-2.5 rounded-lg text-xs font-bold transition-all duration-300 ${
              isConnected
                ? "bg-error/10 text-error border border-error/20 hover:bg-error/20"
                : "bg-primary text-on-primary hover:opacity-90 shadow-glow"
            } disabled:opacity-50`}
          >
            {isConnected ? "Disconnect" : "Monitor"}
          </button>
        </motion.div>

        {/* ── State Bar ── */}
        <AnimatePresence>
          {isConnected && currentState && (
            <motion.div
              key="state-bar"
              initial={{ opacity: 0, scale: 0.98, y: -8 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.98, y: -8 }}
              transition={{ duration: 0.35, ease: "easeOut" }}
              className="bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-4 mb-8 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 transition-all duration-300"
            >
            <div className="flex items-center gap-4">
              <div className="relative w-8 h-8 flex items-center justify-center">
                <div className="absolute inset-0 border border-primary/30 rounded-full animate-spin [animation-duration:3s]" />
                <ShieldAlert className="h-4 w-4 text-primary" />
              </div>
              <span className="text-xs font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-widest font-body">
                Operational Phase: <span className="text-on-surface dark:text-[#F0F0F5]">{currentState.replace(/_/g, " ")}</span>
              </span>
            </div>

            <div className="flex gap-3">
              {currentState === "awaiting_approval" && (
                <button
                  onClick={handleApprove}
                  disabled={isApproving}
                  className="px-6 py-2 bg-primary text-on-primary font-bold text-[10px] tracking-widest uppercase hover:opacity-90 transition-all duration-300 disabled:opacity-50 rounded-lg shadow-glow"
                >
                  {isApproving ? "Authorizing..." : "Authorize Execution"}
                </button>
              )}
              <button onClick={reconnect} className="p-2 text-on-surface-variant dark:text-[#8A8A9E] hover:text-on-surface dark:hover:text-[#F0F0F5] transition-all duration-300 rounded-lg hover:bg-surface-container dark:hover:bg-[#1A1A24]">
                <RefreshCcw size={16} />
              </button>
              <button onClick={clearEvents} className="p-2 text-on-surface-variant dark:text-[#8A8A9E] hover:text-error transition-all duration-300 rounded-lg hover:bg-error/5">
                <Trash2 size={16} />
              </button>
            </div>
          </motion.div>
        )}
        </AnimatePresence>

        {/* ── Stats Grid ── */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {stats.map((s, i) => (
            <StatCard key={s.label} {...s} index={i} />
          ))}
        </div>

        {/* ── Bento Grid ── */}
        <div className="grid grid-cols-12 gap-6 mb-8">
          {/* Network Intelligence Feed */}
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
                    {/* System Overview */}
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

                  {/* Recent Engagements */}
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
                    {recentEngagements.length === 0 ? (
                      <div className="text-center py-6 text-on-surface-variant/40 dark:text-[#8A8A9E]/40 text-xs font-mono uppercase">
                        No engagements yet
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {recentEngagements.slice(0, 5).map((eng) => (
                          <div
                            key={eng.id}
                            className="flex items-center justify-between px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08] rounded-lg hover:bg-surface-container-high dark:hover:bg-[#1A1A24] transition-all duration-300 cursor-pointer"
                            onClick={() => {
                              connectEngagement(eng.id);
                            }}
                          >
                            <div className="flex items-center gap-3">
                              <div className={`w-2 h-2 rounded-full ${
                                eng.status === 'complete' ? 'bg-green-500' :
                                eng.status === 'failed' ? 'bg-error' :
                                eng.status === 'scanning' ? 'bg-primary animate-pulse' :
                                'bg-amber-400'
                              }`} />
                              <div>
                                <div className="text-xs text-on-surface dark:text-[#F0F0F5] font-mono truncate max-w-[200px]">{eng.target_url}</div>
                                <div className="text-[10px] text-on-surface-variant dark:text-[#8A8A9E] uppercase">{eng.status.replace(/_/g, " ")}</div>
                              </div>
                            </div>
                            <div className="flex items-center gap-3">
                              {eng.findings_count > 0 && (
                                <span className="text-[10px] font-mono text-primary">{eng.findings_count} findings</span>
                              )}
                              <ChevronRight size={12} className="text-on-surface-variant dark:text-[#8A8A9E]" />
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
                      className="flex items-center gap-2 px-4 py-2 bg-primary text-on-primary text-xs font-bold uppercase tracking-widest hover:opacity-90 transition-all duration-300 shadow-glow rounded-lg"
                    >
                      <Target size={14} />
                      New Engagement
                    </button>
                    <button
                      onClick={() => router.push("/findings")}
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
                  {/* Live scan status */}
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

                  {/* Scanner steps */}
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
                  {findings.map((event, i) => <ThreatFeedRow key={i} event={event} />)}
                </motion.div>
              )}
              </AnimatePresence>
            </div>
          </motion.div>

          {/* Scanner Activity Panel */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.3 }}
            className="col-span-12 lg:col-span-4 bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl overflow-hidden transition-all duration-300 hover:border-primary/20"
          >
            <div className="flex items-center gap-2 px-5 py-4 border-b border-outline-variant dark:border-[#ffffff08]">
              <Terminal size={16} className="text-primary" />
              <h2 className="text-sm font-headline font-medium text-on-surface dark:text-[#F0F0F5] tracking-wide uppercase">Scanner Activity</h2>
              {isConnected && scannerActivities.some((a) => a.status === "started" || a.status === "in_progress") && (
                <div className="ml-auto flex items-center gap-1.5">
                  <motion.span
                    className="relative flex h-2 w-2"
                    animate={{ scale: [1, 1.3, 1], opacity: [1, 0.7, 1] }}
                    transition={{ duration: 1.2, repeat: Infinity, ease: "easeInOut" }}
                  >
                    <span className="absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
                  </motion.span>
                  <span className="text-[10px] font-mono text-primary uppercase">Live</span>
                </div>
              )}
            </div>
            <div className="p-5">
              <AnimatePresence mode="wait">
                {isConnected ? (
                  <motion.div
                    key="timeline"
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -6 }}
                    transition={{ duration: 0.3 }}
                  >
                    <ScanStepTimeline currentState={currentState} activities={scannerActivities} />
                  </motion.div>
                ) : (
                  <motion.div
                    key="empty"
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -6 }}
                    transition={{ duration: 0.3 }}
                    className="flex flex-col items-center justify-center py-10 text-on-surface-variant/40 dark:text-[#8A8A9E]/40 gap-3"
                  >
                    <Terminal size={24} />
                    <p className="text-[10px] font-mono uppercase tracking-widest text-center">
                      Connect to an engagement to view scanner activity
                    </p>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </motion.div>

          {/* Execution Timeline */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.4 }}
            className="col-span-12 bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl overflow-hidden transition-all duration-300 hover:border-primary/20"
          >
            <div className="flex items-center gap-2 px-5 py-4 border-b border-outline-variant dark:border-[#ffffff08]">
              <Clock size={16} className="text-primary" />
              <h2 className="text-sm font-headline font-medium text-on-surface dark:text-[#F0F0F5] tracking-wide uppercase">Execution Timeline</h2>
            </div>
            <div className="p-1">
              <AnimatePresence mode="wait">
                {isConnected && timelineEvents.length > 0 ? (
                  <motion.div
                    key="timeline-chart"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.3 }}
                  >
                    <Suspense fallback={
                      <div className="h-[240px] flex items-center justify-center bg-surface-container dark:bg-[#1A1A24]">
                        <Loader2 className="h-6 w-6 animate-spin text-primary" />
                      </div>
                    }>
                      <ExecutionTimeline events={timelineEvents} engagementStart={engagementStart} />
                    </Suspense>
                  </motion.div>
                ) : (
                  <motion.div
                    key="timeline-empty"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.3 }}
                    className="h-[240px] flex flex-col items-center justify-center bg-surface-container dark:bg-[#1A1A24] text-on-surface-variant/40 dark:text-[#8A8A9E]/40 gap-3 rounded-lg"
                  >
                    <Clock size={24} />
                    <p className="text-[10px] font-mono uppercase tracking-widest">Connect to an engagement to view execution timeline</p>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </motion.div>
        </div>

        {/* ── Visualization Section ── */}
        <div className="space-y-6">
          {/* Attack Path Graph */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.5 }}
            className="bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl overflow-hidden transition-all duration-300 hover:border-primary/20"
          >
            <div className="flex items-center gap-2 px-5 py-4 border-b border-outline-variant dark:border-[#ffffff08]">
              <GitBranch size={16} className="text-primary" />
              <h2 className="text-sm font-headline font-medium text-on-surface dark:text-[#F0F0F5] tracking-wide uppercase">Attack Path Visualization</h2>
              {isConnected && attackPaths.nodes && (
                <span className="ml-auto text-[10px] font-mono text-on-surface-variant dark:text-[#8A8A9E]">{attackPaths.nodes.length} nodes</span>
              )}
            </div>
            <div className="p-1">
              <AnimatePresence mode="wait">
                {isConnected && attackPaths.nodes ? (
                  <motion.div
                    key="attack-graph"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.3 }}
                  >
                    <Suspense fallback={
                      <div className="h-[420px] flex items-center justify-center bg-surface-container dark:bg-[#1A1A24]">
                        <Loader2 className="h-6 w-6 animate-spin text-primary" />
                      </div>
                    }>
                      <AttackPathGraph nodes={attackPaths.nodes} edges={attackPaths.edges} />
                    </Suspense>
                  </motion.div>
                ) : (
                  <motion.div
                    key="attack-empty"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.3 }}
                    className="h-[420px] flex flex-col items-center justify-center bg-surface-container dark:bg-[#1A1A24] text-on-surface-variant/40 dark:text-[#8A8A9E]/40 gap-3 rounded-lg"
                  >
                    <GitBranch size={24} />
                    <p className="text-[10px] font-mono uppercase tracking-widest">Connect to an engagement to visualize attack paths</p>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </motion.div>

          {/* Tool Performance Metrics */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.6 }}
            className="bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl overflow-hidden transition-all duration-300 hover:border-primary/20"
          >
            <div className="flex items-center gap-2 px-5 py-4 border-b border-outline-variant dark:border-[#ffffff08]">
              <BarChart3 size={16} className="text-primary" />
              <h2 className="text-sm font-headline font-medium text-on-surface dark:text-[#F0F0F5] tracking-wide uppercase">Tool Performance Metrics</h2>
            </div>
            <div className="p-5">
              <Suspense fallback={
                <div className="h-[200px] flex items-center justify-center">
                  <Loader2 className="h-6 w-6 animate-spin text-primary" />
                </div>
              }>
                <ToolPerformanceMetrics metrics={toolMetrics} days={7} />
              </Suspense>
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  );
}
