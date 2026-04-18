"use client";

/**
 * Dashboard Page with Real-Time Engagement Updates
 * 
 * Demonstrates WebSocket connection and real-time UI updates.
 * 
 * Requirements: 31.5
 */

import { useState } from "react";
import { useEngagementEvents } from "@/lib/use-engagement-events";
import { WebSocketEvent } from "@/lib/websocket-events";
import { motion, AnimatePresence } from "framer-motion";
import { 
  Activity, 
  Terminal, 
  ShieldAlert, 
  RefreshCcw, 
  Trash2, 
  ChevronRight, 
  Zap,
  CheckCircle2,
  XCircle,
  Database,
  Cpu,
  Clock
} from "lucide-react";

export default function DashboardPage() {
  const [engagementId, setEngagementId] = useState<string>("");
  const [isConnected, setIsConnected] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [approveError, setApproveError] = useState<string | null>(null);
  const [approveSuccess, setApproveSuccess] = useState<string | null>(null);
  const {
    events,
    currentState,
    isConnected: wsConnected,
    reconnect,
    clearEvents,
  } = useEngagementEvents({
    engagementId,
    enabled: isConnected && !!engagementId,
    pollingInterval: 2000,
    onEvent: (event: WebSocketEvent) => {
      // Handle event - no logging in production
    },
    onError: (err: Error) => {
      console.error("WebSocket error:", err);
    },
  });

  // Handle approve findings
  const handleApprove = async () => {
    if (!engagementId) return;

    setIsApproving(true);
    setApproveError(null);
    setApproveSuccess(null);

    try {
      const response = await fetch(`/api/engagement/${engagementId}/approve`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Failed to approve engagement");
      }

      setApproveSuccess("Findings approved! Scan job has been queued.");
    } catch (err) {
      setApproveError(err instanceof Error ? err.message : "Failed to approve engagement");
    } finally {
      setIsApproving(false);
    }
  };

  // Group events by type
  const eventsByType = events.reduce(
    (acc, event) => {
      const type = event.type;
      if (!acc[type]) {
        acc[type] = [];
      }
      acc[type].push(event);
      return acc;
    },
    {} as Record<string, WebSocketEvent[]>
  );

  // Get severity color
  const getSeverityColor = (severity: string): string => {
    switch (severity.toUpperCase()) {
      case "CRITICAL":
        return "text-red-500";
      case "HIGH":
        return "text-orange-500";
      case "MEDIUM":
        return "text-yellow-500";
      case "LOW":
        return "text-blue-500";
      default:
        return "text-gray-400";
    }
  };

  // Get event type badge icon/color
  const getEventMeta = (type: string) => {
    switch (type) {
      case "finding_discovered":
        return { icon: ShieldAlert, color: "text-argus-magenta", bg: "bg-argus-magenta/10", border: "border-argus-magenta/20" };
      case "state_transition":
        return { icon: RefreshCcw, color: "text-argus-indigo", bg: "bg-argus-indigo/10", border: "border-argus-indigo/20" };
      case "rate_limit_event":
        return { icon: Clock, color: "text-argus-cyan", bg: "bg-argus-cyan/10", border: "border-argus-cyan/20" };
      case "tool_executed":
        return { icon: Cpu, color: "text-argus-indigo", bg: "bg-argus-indigo/10", border: "border-argus-indigo/20" };
      case "job_started":
        return { icon: Zap, color: "text-argus-cyan", bg: "bg-argus-cyan/10", border: "border-argus-cyan/20" };
      case "job_completed":
        return { icon: CheckCircle2, color: "text-green-400", bg: "bg-green-400/10", border: "border-green-400/20" };
      case "error":
        return { icon: XCircle, color: "text-red-400", bg: "bg-red-400/10", border: "border-red-400/20" };
      default:
        return { icon: Activity, color: "text-muted-foreground", bg: "bg-muted/10", border: "border-border" };
    }
  };

  return (
    <div className="py-8 px-10">
      <div className="max-w-7xl mx-auto flex flex-col gap-8">
        
        {/* Connection Header Block */}
        <div className="prism-glass p-8 rounded-3xl flex flex-col md:flex-row gap-6 items-center justify-between">
          <div className="flex flex-col gap-1">
            <h1 className="text-3xl font-extrabold tracking-tight">Intelligence Dashboard</h1>
            <div className="flex items-center gap-2 text-sm text-muted-foreground font-medium">
              <div className={`w-2 h-2 rounded-full ${wsConnected ? "bg-argus-cyan" : "bg-red-500"} animate-pulse`} />
              {wsConnected ? "System Online" : "System Offline"}
            </div>
          </div>

          <div className="flex gap-3 w-full md:w-auto">
            <div className="relative flex-1 md:w-80">
              <Database className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                type="text"
                placeholder="Enter Engagement ID..."
                value={engagementId}
                onChange={(e) => setEngagementId(e.target.value)}
                className="w-full pl-10 pr-4 py-3 bg-secondary/50 border border-border rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/50 text-sm"
              />
            </div>
            <button
              onClick={() => setIsConnected(!isConnected)}
              disabled={!engagementId}
              className={`px-6 py-3 rounded-xl font-bold transition-all ${
                isConnected
                  ? "bg-red-500/10 text-red-500 border border-red-500/20 hover:bg-red-500/20"
                  : "bg-primary text-primary-foreground hover:shadow-[0_0_20px_rgba(59,130,246,0.5)]"
              } disabled:opacity-50 text-sm`}
            >
              {isConnected ? "Halt" : "Monitor"}
            </button>
          </div>
        </div>

        {/* Action Bar */}
        {currentState && (
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            className="prism-glass p-4 rounded-2xl flex flex-col md:flex-row md:items-center justify-between gap-4 border-primary/20"
          >
            <div className="flex items-center gap-3 ml-4">
              <div className="prism-scanner w-8 h-8">
                <ShieldAlert className="h-4 w-4 text-accent" />
              </div>
              <span className="text-sm font-semibold text-muted-foreground uppercase tracking-widest">
                Current Phase: <span className="text-foreground">{currentState.replace(/_/g, " ")}</span>
              </span>
            </div>

            {/* Feedback Messages */}
            <div className="flex flex-col md:flex-row items-center gap-3 md:mr-4">
              {approveSuccess && (
                <motion.div
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="flex items-center gap-2 px-4 py-2 bg-green-500/10 border border-green-500/30 text-green-400 text-xs font-medium rounded-xl"
                >
                  <CheckCircle2 className="h-4 w-4" />
                  {approveSuccess}
                </motion.div>
              )}
              {approveError && (
                <motion.div
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="flex items-center gap-2 px-4 py-2 bg-red-500/10 border border-red-500/30 text-red-400 text-xs font-medium rounded-xl"
                >
                  <XCircle className="h-4 w-4" />
                  {approveError}
                </motion.div>
              )}
            </div>

            <div className="flex items-center gap-4 md:mr-4">
              {currentState === "awaiting_approval" && (
                <button
                  onClick={handleApprove}
                  disabled={isApproving}
                  className="px-6 py-2 bg-accent text-white rounded-xl font-bold text-xs hover:shadow-[0_0_20px_rgba(6,182,212,0.5)] transition-all disabled:opacity-50"
                >
                  {isApproving ? "Approving..." : "Authorize Execution"}
                </button>
              )}
              <button onClick={reconnect} className="p-2 text-muted-foreground hover:text-foreground transition-colors"><RefreshCcw className="h-4 w-4" /></button>
              <button onClick={clearEvents} className="p-2 text-muted-foreground hover:text-red-400 transition-colors"><Trash2 className="h-4 w-4" /></button>
            </div>
          </motion.div>
        )}

        {/* Stats Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          {[
            { label: "Detected Vectors", val: eventsByType["finding_discovered"]?.length || 0, color: "text-argus-magenta" },
            { label: "Operational Loops", val: eventsByType["state_transition"]?.length || 0, color: "text-argus-indigo" },
            { label: "Tool Executions", val: eventsByType["tool_executed"]?.length || 0, color: "text-argus-cyan" },
            { label: "Network Events", val: events.length, color: "text-foreground" }
          ].map((stat, i) => (
            <div key={i} className="prism-glass p-6 rounded-2xl">
              <p className="text-xs font-bold text-muted-foreground uppercase tracking-widest mb-1">{stat.label}</p>
              <p className={`text-4xl font-extrabold tracking-tight ${stat.color}`}>{stat.val}</p>
            </div>
          ))}
        </div>

        {/* Real-time Feed Block */}
        <div className="prism-glass rounded-3xl overflow-hidden flex flex-col">
          <div className="px-8 py-5 border-b border-border flex items-center gap-3 bg-secondary/20">
            <Terminal className="h-5 w-5 text-muted-foreground" />
            <h2 className="text-sm font-bold uppercase tracking-widest">Intelligence Feed</h2>
          </div>
          
          <div className="flex flex-col h-[500px] overflow-y-auto p-4 gap-3 bg-black/20">
            {events.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-muted-foreground gap-4 opacity-50">
                <Cpu className="h-12 w-12 animate-pulse" />
                <p className="text-sm font-medium">Standalone system waiting for signal...</p>
              </div>
            ) : (
              <AnimatePresence initial={false}>
                {events.map((event, index) => {
                  const meta = getEventMeta(event.type);
                  return (
                    <motion.div 
                      key={`${event.type}-${index}`}
                      initial={{ opacity: 0, x: -20 }}
                      animate={{ opacity: 1, x: 0 }}
                      className={`p-4 rounded-xl border ${meta.border} ${meta.bg} flex items-start gap-4 transition-all hover:bg-white/5 group`}
                    >
                      <div className={`mt-0.5 p-2 rounded-lg ${meta.bg} ${meta.color}`}>
                        <meta.icon className="h-4 w-4" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-3 mb-1">
                          <span className={`text-[10px] font-black uppercase tracking-widest ${meta.color}`}>
                            {event.type.replace(/_/g, " ")}
                          </span>
                          <span className="text-[10px] font-mono text-muted-foreground opacity-50">
                            {new Date(event.timestamp).toLocaleTimeString()}
                          </span>
                        </div>
                        <EventDetails event={event} getSeverityColor={getSeverityColor} />
                      </div>
                      <ChevronRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                    </motion.div>
                  );
                })}
              </AnimatePresence>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}

/**
 * Event details component
 */
function EventDetails({
  event,
  getSeverityColor,
}: {
  event: WebSocketEvent;
  getSeverityColor: (severity: string) => string;
}) {
  switch (event.type) {
    case "finding_discovered":
      return (
        <div className="text-sm">
          <p>
            <span className={getSeverityColor(event.data.severity as string)}>
              {event.data.severity as string}
            </span>
            {" - "}
            <span className="text-white">{event.data.finding_type as string}</span>
          </p>
          <p className="text-slate-400 text-xs mt-1 truncate">
            {event.data.endpoint as string}
          </p>
          <p className="text-slate-500 text-xs mt-1">
            Confidence: {((event.data.confidence as number) * 100).toFixed(0)}% | Tool: {event.data.source_tool as string}
          </p>
        </div>
      );

    case "state_transition":
      return (
        <div className="text-sm">
          <p>
            <span className="text-slate-400">{event.data.from_state as string}</span>
            <span className="mx-2">→</span>
            <span className="text-blue-300">{event.data.to_state as string}</span>
          </p>
          {(event.data.reason as string | null) && (
            <p className="text-slate-500 text-xs mt-1">
              Reason: {event.data.reason as string}
            </p>
          )}
        </div>
      );

    case "rate_limit_event":
      return (
        <div className="text-sm">
          <p>
            Domain: <span className="text-white">{event.data.domain as string}</span>
          </p>
          <p className="text-slate-400 text-xs mt-1">
            {event.data.message as string} | RPS: {(event.data.current_rps as number).toFixed(1)}
          </p>
        </div>
      );

    case "tool_executed":
      return (
        <div className="text-sm">
          <p>
            Tool: <span className="text-purple-300">{event.data.tool_name as string}</span>
            {" | "}
            <span className={event.data.success ? "text-green-400" : "text-red-400"}>
              {event.data.success ? "Success" : "Failed"}
            </span>
          </p>
          <p className="text-slate-500 text-xs mt-1">
            Duration: {event.data.duration_ms as number}ms | Findings: {event.data.findings_count as number}
          </p>
        </div>
      );

    case "job_started":
      return (
        <div className="text-sm">
          <p>
            Job: <span className="text-green-300">{event.data.job_type as string}</span>
          </p>
          {(event.data.target as string | null) && (
            <p className="text-slate-400 text-xs mt-1 truncate">
              Target: {event.data.target as string}
            </p>
          )}
        </div>
      );

    case "job_completed":
      return (
        <div className="text-sm">
          <p>
            Job: <span className="text-gray-300">{event.data.job_type as string}</span>
            {" | "}
            <span className={event.data.status === "success" ? "text-green-400" : "text-red-400"}>
              {event.data.status as string}
            </span>
          </p>
          <p className="text-slate-500 text-xs mt-1">
            Duration: {event.data.duration_ms as number}ms | Findings: {event.data.findings_count as number}
          </p>
        </div>
      );

    case "error":
      return (
        <div className="text-sm">
          <p className="text-red-400">{event.data.error_message as string}</p>
          <p className="text-slate-500 text-xs mt-1">
            Code: {event.data.error_code as string}
          </p>
        </div>
      );

    default:
      return (
        <pre className="text-xs text-slate-400">
          {JSON.stringify(event.data, null, 2)}
        </pre>
      );
  }
}
