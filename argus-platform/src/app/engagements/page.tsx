"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { motion } from "framer-motion";
import { log } from "@/lib/logger";
import {
  Shield,
  Globe,
  GitBranch,
  AlertTriangle,
  Loader2,
  Target,
  ArrowRight,
  ShieldCheck,
  Zap,
  Bomb,
  Eye,
  Trash2,
  BarChart3,
  Activity,
  Server,
  Cpu,
  X,
  ChevronDown,
  ChevronUp,
  StopCircle,
  RefreshCw,
  Brain,
  MessageSquare,
  Edit3,
  CheckCircle,
  AlertCircle,
} from "lucide-react";
import ScanModeHelp from "@/components/ui-custom/ScanModeHelp";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { ScrollReveal } from "@/components/animations/ScrollReveal";
import { StaggerContainer, StaggerItem } from "@/components/animations/StaggerContainer";
import SkeletonLoader from "@/components/ui-custom/SkeletonLoader";

interface Engagement {
  id: string;
  target_url: string;
  status: string;
  scan_type: string;
  created_at: string;
  completed_at: string | null;
  created_by_email: string;
  findings_count: number;
  critical_count: number;
}

interface URLHistoryItem {
  url: string;
  timestamp: number;
  scanType: "url" | "repo";
}

const HISTORY_KEY = "argus:url-history";
const MAX_HISTORY = 10;

const getDomain = (url: string) => {
  try {
    return new URL(url.startsWith('http') ? url : `https://${url}`).hostname;
  } catch {
    return url;
  }
};

const useURLHistory = () => {
  const [history, setHistory] = useState<URLHistoryItem[]>([]);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(HISTORY_KEY);
      if (stored) {
        setHistory(JSON.parse(stored));
      }
    } catch {
      // ignore parse errors
    }
  }, []);

  const addToHistory = useCallback((url: string, scanType: "url" | "repo") => {
    setHistory((prev) => {
      const filtered = prev.filter((item) => item.url !== url);
      const updated = [{ url, timestamp: Date.now(), scanType }, ...filtered].slice(0, MAX_HISTORY);
      try {
        localStorage.setItem(HISTORY_KEY, JSON.stringify(updated));
      } catch {
        // ignore storage errors
      }
      return updated;
    });
  }, []);

  const removeFromHistory = useCallback((url: string) => {
    setHistory((prev) => {
      const updated = prev.filter((item) => item.url !== url);
      try {
        localStorage.setItem(HISTORY_KEY, JSON.stringify(updated));
      } catch {
        // ignore storage errors
      }
      return updated;
    });
  }, []);

  const clearHistory = useCallback(() => {
    setHistory([]);
    try {
      localStorage.removeItem(HISTORY_KEY);
    } catch {
      // ignore storage errors
    }
  }, []);

  return { history, addToHistory, removeFromHistory, clearHistory };
};

const statusConfig: Record<string, { color: string; bg: string; label: string }> = {
  created: { color: "text-blue-500", bg: "bg-blue-500/10", label: "Created" },
  recon: { color: "text-amber-500", bg: "bg-amber-500/10", label: "Recon" },
  awaiting_approval: { color: "text-purple-500", bg: "bg-purple-500/10", label: "Awaiting Approval" },
  scanning: { color: "text-primary", bg: "bg-primary/10", label: "Scanning" },
  analyzing: { color: "text-cyan-500", bg: "bg-cyan-500/10", label: "Analyzing" },
  reporting: { color: "text-pink-500", bg: "bg-pink-500/10", label: "Reporting" },
  complete: { color: "text-green-500", bg: "bg-green-500/10", label: "Complete" },
  failed: { color: "text-error", bg: "bg-error/10", label: "Failed" },
  paused: { color: "text-on-surface-variant", bg: "bg-surface-container", label: "Paused" },
};

export default function EngagementsPage() {
  useEffect(() => {
    log.pageMount("Engagements");
    return () => log.pageUnmount("Engagements");
  }, []);

  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();

  const [scanType, setScanType] = useState<"url" | "repo">("url");
  const [target, setTarget] = useState("");
  const [scanAggressiveness, setScanAggressiveness] = useState("default");
  const [agentMode, setAgentMode] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [progressStep, setProgressStep] = useState("");
  const [error, setError] = useState("");
  const [stoppingId, setStoppingId] = useState<string | null>(null);
  const [rescannings, setRescannings] = useState<Set<string>>(new Set());
  const [showAllHistory, setShowAllHistory] = useState(false);
  const [settingsLoading, setSettingsLoading] = useState(true);

  // Natural Language scan config state
  const [configMode, setConfigMode] = useState<"standard" | "nl">("standard");
  const [nlIntent, setNlIntent] = useState("");
  const [nlLoading, setNlLoading] = useState(false);
  const [nlResult, setNlResult] = useState<Record<string, string | boolean | string[]> | null>(null);
  const [nlError, setNlError] = useState("");
  const [nlIsFallback, setNlIsFallback] = useState(false);

  const { history, addToHistory, removeFromHistory, clearHistory } = useURLHistory();

  // Live engagements state
  const [liveEngagements, setLiveEngagements] = useState<Engagement[]>([]);
  const [liveLoading, setLiveLoading] = useState(false);

  // Load user's default aggressiveness from settings
  useEffect(() => {
    if (status === "unauthenticated") {
      signIn();
    }
    if (status === "authenticated") {
      fetch("/api/settings")
        .then((r) => r.json())
        .then((data) => {
          if (data.settings?.scan_aggressiveness) {
            setScanAggressiveness(data.settings.scan_aggressiveness);
          }
        })
        .catch(() => {})
        .finally(() => setSettingsLoading(false));
    } else if (status === "unauthenticated") {
      setSettingsLoading(false);
    }
  }, [status]);

  // Fetch live engagements
  useEffect(() => {
    if (status !== "authenticated") return;

    const fetchEngagements = async () => {
      setLiveLoading(true);
      try {
        const response = await fetch("/api/engagements?limit=10");
        if (response.ok) {
          const data = await response.json();
          setLiveEngagements(data.engagements || []);
        }
      } catch (err) {
        console.error("Failed to load engagements:", err);
      } finally {
        setLiveLoading(false);
      }
    };

    fetchEngagements();
    const interval = setInterval(fetchEngagements, 10000);
    return () => clearInterval(interval);
  }, [status]);

  const analyticsData = useMemo(() => {
    return liveEngagements.slice(0, 7).map((eng) => ({
      name: eng.target_url?.replace(/^https?:\/\//, "").substring(0, 10) || "Unknown",
      findings: eng.findings_count || 0,
      critical: eng.critical_count || 0,
    }));
  }, [liveEngagements]);

  if (status === "loading") {
    return <SkeletonLoader className="min-h-screen" />;
  }

  if (!session) return null;

  const handleParseIntent = async () => {
    setNlError("");
    setNlResult(null);
    setNlIsFallback(false);

    if (!nlIntent.trim()) {
      setNlError("Please describe what you want to scan");
      return;
    }

    setNlLoading(true);
    try {
      const response = await fetch("/api/engagements/parse-intent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ intent: nlIntent.trim() }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "Failed to parse scan intent");
      }

      if (data.error) {
        setNlError(data.error);
        return;
      }

      if (data._fallback) {
        setNlIsFallback(true);
      }

      setNlResult(data);
    } catch (err) {
      setNlError(err instanceof Error ? err.message : "Failed to parse intent");
    } finally {
      setNlLoading(false);
    }
  };

  const handleNlStartScan = async () => {
    if (!nlResult?.target_url) return;

    setError("");
    setIsLoading(true);
    setProgressStep("Creating engagement from parsed config...");

    try {
      const response = await fetch("/api/engagement/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          targetUrl: String(nlResult.target_url),
          scanType: String(nlResult.scan_type || "url"),
          scanAggressiveness: String(nlResult.aggressiveness || "default"),
          agentMode: Boolean(nlResult.agent_mode),
          authorization: "AUTHORIZED OPERATIONAL SCAN",
          authorizedScope: {},
          scanMode: "agent",
        }),
      });

      if (response.status === 401) {
        signIn();
        return;
      }

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Failed to initiate engagement");
      }

      const engagementId = data.engagement?.id || data.engagement_id;
      if (!engagementId) {
        throw new Error("Invalid engagement response - no ID received");
      }

      setProgressStep("Redirecting to dashboard...");
      showToast("success", "Engagement launched from natural language config");
      addToHistory(String(nlResult.target_url), String(nlResult.scan_type || "url") as "url" | "repo");
      router.push(`/dashboard?engagement=${engagementId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Launch failed");
      showToast("error", err instanceof Error ? err.message : "System failure");
    } finally {
      setIsLoading(false);
      setProgressStep("");
    }
  };

  const handleNlEditDetails = () => {
    if (nlResult?.target_url) {
      setTarget(String(nlResult.target_url));
    }
    if (nlResult?.scan_type) {
      setScanType(String(nlResult.scan_type) as "url" | "repo");
    }
    if (nlResult?.aggressiveness) {
      setScanAggressiveness(String(nlResult.aggressiveness));
    }
    if (nlResult?.agent_mode !== undefined) {
      setAgentMode(Boolean(nlResult.agent_mode));
    }
    setConfigMode("standard");
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);
    setProgressStep("Initializing...");

    if (!target) {
      setError("Target identifier required");
      setIsLoading(false);
      setProgressStep("");
      return;
    }

    try {
      setProgressStep("Validating target...");

      // Validate URL format first
      let validatedScope;
      try {
        validatedScope = scanType === "url"
          ? { domains: [new URL(target.startsWith('http') ? target : `https://${target}`).hostname], ipRanges: [] }
          : { domains: [], ipRanges: [] };
      } catch {
        throw new Error("Invalid target format");
      }

      setProgressStep("Creating engagement...");
      const response = await fetch("/api/engagement/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          targetUrl: target,
          scanType: scanType,
          scanAggressiveness: scanAggressiveness,
          agentMode: agentMode,
          authorization: "AUTHORIZED OPERATIONAL SCAN",
          authorizedScope: validatedScope,
        }),
      });

      if (response.status === 401) {
        signIn();
        return;
      }

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Failed to initiate engagement");
      }

      const engagementId = data.engagement?.id || data.engagement_id;

      // Validate engagement ID before redirecting
      if (!engagementId) {
        throw new Error("Invalid engagement response - no ID received");
      }

      setProgressStep("Redirecting to dashboard...");
      showToast("success", "Operation initiated");
      addToHistory(target, scanType);
      router.push(`/dashboard?engagement=${engagementId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Handshake failed");
      showToast("error", err instanceof Error ? err.message : "System failure");
    } finally {
      setIsLoading(false);
      setProgressStep("");
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this engagement and all its findings?")) return;
    try {
      const response = await fetch(`/api/engagement/${id}/delete`, {
        method: "DELETE",
      });
      if (response.ok) {
        showToast("success", "Engagement deleted");
        setLiveEngagements((prev) => prev.filter((e) => e.id !== id));
        const res = await fetch("/api/engagements", { cache: "no-store" });
        if (res.ok) {
          const data = await res.json();
          setLiveEngagements(data.engagements || []);
        }
      } else {
        const data = await response.json();
        showToast("error", data.error || "Cannot delete engagement in progress");
      }
    } catch (err) {
      showToast("error", "Failed to delete engagement");
    }
  };

  const handleStop = async (id: string) => {
    if (!confirm("Stop this scan?")) return;
    setStoppingId(id);
    try {
      const response = await fetch(`/api/engagement/${id}/stop`, { method: "POST" });
      if (response.ok) {
        showToast("success", "Scan stopped");
        const res = await fetch("/api/engagements", { cache: "no-store" });
        if (res.ok) {
          const data = await res.json();
          setLiveEngagements(data.engagements || []);
        }
      } else {
        const data = await response.json().catch(() => ({}));
        showToast("error", data.error || "Failed to stop scan");
      }
    } catch {
      showToast("error", "Failed to stop scan");
    } finally {
      setStoppingId(null);
    }
  };

  const handleRescan = async (id: string) => {
    setRescannings((prev) => new Set(prev).add(id));
    try {
      const response = await fetch(`/api/engagement/${id}/rescan`, { method: "POST" });
      if (response.ok) {
        showToast("success", "Rescan triggered");
        const res = await fetch("/api/engagements", { cache: "no-store" });
        if (res.ok) {
          const data = await res.json();
          setLiveEngagements(data.engagements || []);
        }
      } else {
        const data = await response.json().catch(() => ({}));
        showToast("error", data.error || "Failed to rescan");
      }
    } catch {
      showToast("error", "Failed to rescan");
    } finally {
      setRescannings((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  const getScanProgress = (status: string) => {
    const order = ["created", "recon", "awaiting_approval", "scanning", "analyzing", "reporting", "complete"];
    const idx = order.indexOf(status);
    if (idx === -1) return 0;
    return Math.round(((idx + 1) / order.length) * 100);
  };

  return (
    <div className="min-h-screen bg-background dark:bg-[#0A0A0F] matrix-grid">
      <style jsx>{`
        @keyframes shimmer {
          0% { background-position: -200% 0; }
          100% { background-position: 200% 0; }
        }
        .shimmer {
          background: linear-gradient(90deg, transparent 0%, rgba(103, 32, 255, 0.08) 50%, transparent 100%);
          background-size: 200% 100%;
          animation: shimmer 1.5s infinite;
        }
      `}</style>
      <div className="max-w-[1440px] mx-auto px-4 sm:px-6 py-8">
        {/* ── Header ── */}
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mb-8"
        >
          <div className="flex items-center gap-3 mb-2">
            <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
              <ShieldCheck size={18} className="text-primary" />
            </div>
            <span className="text-xs font-body text-on-surface-variant dark:text-[#8A8A9E] tracking-widest uppercase">
              Operations Center
            </span>
          </div>
          <h1 className="text-4xl font-headline font-semibold text-gray-900 dark:text-[#F0F0F5] tracking-tight">
            Security Engagements
          </h1>
          <p className="text-sm font-body text-on-surface-variant dark:text-[#8A8A9E] mt-1">
            Launch penetration tests and monitor active security operations
          </p>
        </motion.div>

        {/* ── Bento Grid ── */}
        <div className="grid grid-cols-12 gap-6">
          {/* New Scan Engagement */}
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className="col-span-12 lg:col-span-7 bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-6 transition-all duration-300 hover:border-primary/20"
          >
            <div className="flex items-center gap-2 mb-6">
              <Target size={18} className="text-primary" />
              <h2 className="text-lg font-headline font-semibold text-on-surface dark:text-[#F0F0F5]">New Scan Engagement</h2>
            </div>

            {/* Configuration Mode Toggle */}
            <div className="flex gap-2 mb-6 p-1 bg-surface-container dark:bg-[#1A1A24] rounded-lg">
              <button
                type="button"
                onClick={() => { setConfigMode("standard"); setNlResult(null); setNlError(""); }}
                className={`flex-1 py-2 text-xs font-bold uppercase tracking-wider rounded-md transition-all duration-300 font-body ${
                  configMode === "standard"
                    ? "bg-primary text-on-primary shadow-glow"
                    : "text-on-surface-variant dark:text-[#8A8A9E] hover:text-on-surface dark:hover:text-[#F0F0F5]"
                }`}
              >
                Standard
              </button>
              <button
                type="button"
                onClick={() => setConfigMode("nl")}
                className={`flex-1 py-2 text-xs font-bold uppercase tracking-wider rounded-md transition-all duration-300 font-body flex items-center justify-center gap-1.5 ${
                  configMode === "nl"
                    ? "bg-primary text-on-primary shadow-glow"
                    : "text-on-surface-variant dark:text-[#8A8A9E] hover:text-on-surface dark:hover:text-[#F0F0F5]"
                }`}
              >
                <MessageSquare size={13} />
                Natural Language
              </button>
            </div>

            {/* Natural Language Mode */}
            {configMode === "nl" ? (
              <div className="space-y-5">
                <div>
                  <label className="block text-[11px] font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-[0.2em] mb-2 font-body">
                    Describe Your Scan Intent
                  </label>
                  <textarea
                    value={nlIntent}
                    onChange={(e) => setNlIntent(e.target.value)}
                    placeholder={`Describe what you want to scan in plain English...

Examples:
• "Scan https://example.com for IDOR and auth bypass vulnerabilities. Focus on high severity."
• "Run a comprehensive scan of my Node.js API at https://api.example.com. Look for injection flaws."
• "Quick security check of https://shop.example.com — prioritize XSS and CSRF."`}
                    rows={5}
                    maxLength={5000}
                    className="w-full px-4 py-3 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] rounded-lg text-sm font-body text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary transition-all duration-300 placeholder:text-on-surface-variant/40 dark:placeholder:text-[#8A8A9E]/40 resize-none"
                  />
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-[10px] font-mono text-on-surface-variant/50 dark:text-[#8A8A9E]/50">
                      {nlIntent.length}/5000
                    </span>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={handleParseIntent}
                  disabled={nlLoading || !nlIntent.trim()}
                  className={`w-full flex items-center justify-center gap-2 py-3 text-xs font-bold uppercase tracking-[0.2em] rounded-lg transition-all duration-300 font-body ${
                    nlLoading
                      ? "bg-transparent text-primary border border-primary/40"
                      : "bg-primary text-on-primary hover:opacity-90 shadow-glow"
                  } disabled:opacity-50`}
                >
                  {nlLoading ? (
                    <>
                      <Loader2 size={14} className="animate-spin" />
                      Parsing Intent...
                    </>
                  ) : (
                    <>
                      <Brain size={14} />
                      Parse Intent
                    </>
                  )}
                </button>

                {/* NL Error */}
                {nlError && (
                  <div className="flex items-start gap-2 p-3 rounded-lg bg-error/10 border border-error/20">
                    <AlertCircle size={16} className="text-error shrink-0 mt-0.5" />
                    <div>
                      <p className="text-xs font-medium text-error uppercase tracking-wider">Parsing Failed</p>
                      <p className="text-xs text-error/80 mt-0.5">{nlError}</p>
                    </div>
                  </div>
                )}

                {/* NL Fallback Warning */}
                {nlIsFallback && nlResult && (
                  <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
                    <AlertTriangle size={16} className="text-amber-500 shrink-0 mt-0.5" />
                    <div>
                      <p className="text-xs font-medium text-amber-500 uppercase tracking-wider">AI Unavailable — Basic Detection Used</p>
                      <p className="text-xs text-amber-400/80 mt-0.5">The scan config was generated using basic URL detection. Please verify the configuration below before proceeding.</p>
                    </div>
                  </div>
                )}

                {/* NL Result Preview */}
                {nlResult && !nlError && (
                  <div className="p-4 rounded-xl bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] space-y-4">
                    <div className="flex items-center gap-2">
                      <CheckCircle size={16} className="text-green-500" />
                      <span className="text-xs font-bold text-on-surface dark:text-[#F0F0F5] uppercase tracking-wider">Parsed Configuration</span>
                    </div>

                    <div className="space-y-2.5">
                      {/* Target URL */}
                      {nlResult.target_url && (
                        <div className="flex items-center gap-2">
                          <Globe size={13} className="text-primary shrink-0" />
                          <span className="text-xs font-mono text-on-surface dark:text-[#F0F0F5] break-all">{String(nlResult.target_url)}</span>
                        </div>
                      )}

                      {/* Scan Type */}
                      {nlResult.scan_type && (
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] font-bold text-on-surface-variant/50 uppercase tracking-wider">Type:</span>
                          <span className="text-xs font-medium text-on-surface dark:text-[#F0F0F5] uppercase bg-surface-container-high dark:bg-[#2A2A35] px-2 py-0.5 rounded">
                            {String(nlResult.scan_type)}
                          </span>
                        </div>
                      )}

                      {/* Aggressiveness */}
                      {nlResult.aggressiveness && (
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] font-bold text-on-surface-variant/50 uppercase tracking-wider">Aggressiveness:</span>
                          <span className={`text-xs font-medium uppercase px-2 py-0.5 rounded ${
                            nlResult.aggressiveness === "extreme"
                              ? "text-error bg-error/10"
                              : nlResult.aggressiveness === "high"
                                ? "text-amber-500 bg-amber-500/10"
                                : "text-primary bg-primary/10"
                          }`}>
                            {String(nlResult.aggressiveness)}
                          </span>
                        </div>
                      )}

                      {/* Priority Classes */}
                      {Array.isArray(nlResult.priority_classes) && (nlResult.priority_classes as string[]).length > 0 && (
                        <div>
                          <span className="text-[10px] font-bold text-on-surface-variant/50 uppercase tracking-wider block mb-1.5">Priority Focus:</span>
                          <div className="flex flex-wrap gap-1.5">
                            {(nlResult.priority_classes as string[]).map((cls: string) => (
                              <span key={cls} className="text-[10px] font-medium text-primary bg-primary/10 px-2 py-0.5 rounded uppercase">
                                {cls}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Tech Stack Hints */}
                      {Array.isArray(nlResult.tech_stack_hints) && (nlResult.tech_stack_hints as string[]).length > 0 && (
                        <div>
                          <span className="text-[10px] font-bold text-on-surface-variant/50 uppercase tracking-wider block mb-1.5">Detected Stack:</span>
                          <div className="flex flex-wrap gap-1.5">
                            {(nlResult.tech_stack_hints as string[]).map((hint: string) => (
                              <span key={hint} className="text-[10px] font-mono text-cyan-500 bg-cyan-500/10 px-2 py-0.5 rounded">
                                {hint}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Auth Config */}
                      {nlResult.auth_config && typeof nlResult.auth_config === "object" && Object.keys(nlResult.auth_config as unknown as Record<string, unknown>).length > 0 && (
                        <div className="flex items-center gap-2">
                          <Shield size={13} className="text-green-500 shrink-0" />
                          <span className="text-[10px] font-medium text-green-500 uppercase tracking-wider">Auth Credentials Detected</span>
                        </div>
                      )}

                      {/* Intent Summary */}
                      {nlResult.intent_summary && (
                        <p className="text-[10px] text-on-surface-variant dark:text-[#8A8A9E] italic border-t border-outline-variant dark:border-[#ffffff08] pt-2">
                          {String(nlResult.intent_summary)}
                        </p>
                      )}
                    </div>

                    {/* Action Buttons */}
                    <div className="flex gap-3 pt-2">
                      <button
                        onClick={handleNlStartScan}
                        className="flex-1 flex items-center justify-center gap-2 py-2.5 bg-primary text-on-primary text-xs font-bold uppercase tracking-wider rounded-lg hover:opacity-90 transition-all duration-300 shadow-glow font-body"
                      >
                        <CheckCircle size={14} />
                        Looks Good, Start Scan
                      </button>
                      <button
                        onClick={handleNlEditDetails}
                        className="flex items-center justify-center gap-2 px-4 py-2.5 border border-outline-variant dark:border-[#ffffff10] text-on-surface-variant dark:text-[#8A8A9E] text-xs font-bold uppercase tracking-wider rounded-lg hover:border-primary/30 hover:text-primary transition-all duration-300 font-body"
                      >
                        <Edit3 size={14} />
                        Edit Details
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              /* Standard Configuration Mode */
              <div className="space-y-5">
            {/* Scan Type */}
            <div className="grid grid-cols-2 gap-4 mb-6">
              <button
                onClick={() => setScanType("url")}
                className={`flex flex-col items-center gap-3 p-5 border rounded-xl transition-all duration-300 ${
                  scanType === "url"
                    ? "border-primary bg-primary/5 shadow-glow"
                    : "border-outline-variant dark:border-[#ffffff10] bg-surface-container dark:bg-[#1A1A24] hover:border-primary/30"
                }`}
              >
                <Globe size={24} className={scanType === "url" ? "text-primary" : "text-on-surface-variant dark:text-[#8A8A9E]"} />
                <span className={`text-[11px] font-bold uppercase tracking-widest font-body ${scanType === "url" ? "text-on-surface dark:text-[#F0F0F5]" : "text-on-surface-variant dark:text-[#8A8A9E]"}`}>Web Application</span>
              </button>
              <button
                onClick={() => setScanType("repo")}
                className={`flex flex-col items-center gap-3 p-5 border rounded-xl transition-all duration-300 ${
                  scanType === "repo"
                    ? "border-primary bg-primary/5 shadow-glow"
                    : "border-outline-variant dark:border-[#ffffff10] bg-surface-container dark:bg-[#1A1A24] hover:border-primary/30"
                }`}
              >
                <GitBranch size={24} className={scanType === "repo" ? "text-primary" : "text-on-surface-variant dark:text-[#8A8A9E]"} />
                <span className={`text-[11px] font-bold uppercase tracking-widest font-body ${scanType === "repo" ? "text-on-surface dark:text-[#F0F0F5]" : "text-on-surface-variant dark:text-[#8A8A9E]"}`}>Repository</span>
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label className="block text-[11px] font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-[0.2em] mb-2 font-body">
                  Target Identifier
                </label>
                {settingsLoading ? (
                  <div className="w-full h-[46px] rounded-lg shimmer" />
                ) : (
                  <div className="relative">
                    <Target className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-on-surface-variant dark:text-[#8A8A9E]" />
                    <input
                      type="text"
                      value={target}
                      onChange={(e) => setTarget(e.target.value)}
                      placeholder={scanType === "url" ? "https://target.com" : "username/repository"}
                      className="w-full pl-10 pr-4 py-3 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] rounded-lg text-sm font-mono text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary transition-all duration-300 placeholder:text-on-surface-variant/40 dark:placeholder:text-[#8A8A9E]/40"
                      required
                    />
                  </div>
                )}
                 {error && (
                   <p className="mt-2 text-[11px] font-mono text-error uppercase tracking-widest font-bold">
                     {error}
                   </p>
                 )}
               </div>

               {/* Recent Targets */}
               {history.length > 0 && (
                 <div>
                   <div className="flex items-center justify-between mb-2">
                     <span className="text-[11px] font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-[0.2em] font-body">
                       Recent Targets
                     </span>
                     <div className="flex items-center gap-2">
                       {history.length > 5 && (
                         <button
                           type="button"
                           onClick={() => setShowAllHistory(!showAllHistory)}
                           className="text-[10px] text-primary hover:underline font-body flex items-center gap-1"
                         >
                           {showAllHistory ? (
                             <>Show less <ChevronUp size={12} /></>
                           ) : (
                             <>Show all ({history.length}) <ChevronDown size={12} /></>
                           )}
                         </button>
                       )}
                       <button
                         type="button"
                         onClick={clearHistory}
                         className="text-[10px] text-error hover:underline font-body"
                       >
                         Clear all
                       </button>
                     </div>
                   </div>
                   <div className="flex flex-wrap gap-2">
                     {(showAllHistory ? history : history.slice(0, 5)).map((item) => (
                       <span
                         key={item.url}
                         className="group flex items-center gap-1.5 px-3 py-1.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] rounded-md text-xs font-mono text-on-surface-variant hover:border-primary/30 cursor-pointer transition-all duration-200"
                         onClick={() => {
                           setTarget(item.url);
                           setScanType(item.scanType);
                         }}
                       >
                         {item.scanType === "repo" ? (
                           <GitBranch size={12} className="text-on-surface-variant/60" />
                         ) : (
                           <Globe size={12} className="text-on-surface-variant/60" />
                         )}
                         <span className="max-w-[150px] truncate">{getDomain(item.url)}</span>
                         <button
                           type="button"
                           onClick={(e) => {
                             e.stopPropagation();
                             removeFromHistory(item.url);
                           }}
                           className="ml-0.5 opacity-0 group-hover:opacity-100 text-on-surface-variant/40 hover:text-error transition-all duration-200"
                         >
                           <X size={10} />
                         </button>
                       </span>
                     ))}
                   </div>
                 </div>
               )}

              {/* Scan Aggressiveness */}
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <label className="text-[11px] font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-[0.2em] font-body">
                    Scan Aggressiveness
                  </label>
                  <ScanModeHelp trigger="icon" />
                </div>
                {settingsLoading ? (
                  <div className="grid grid-cols-3 gap-3">
                    {[1, 2, 3].map((i) => (
                      <div key={i} className="flex flex-col items-center gap-1.5 py-3 border border-outline-variant dark:border-[#ffffff10] rounded-xl">
                        <div className="w-4 h-4 rounded shimmer" />
                        <div className="w-12 h-3 rounded shimmer" />
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="grid grid-cols-3 gap-3">
                    {[
                      { id: "default", name: "Default", icon: <Target size={14} />, color: "text-primary", border: "border-primary", bg: "bg-primary/5" },
                      { id: "high", name: "High", icon: <Zap size={14} />, color: "text-amber-500", border: "border-amber-500", bg: "bg-amber-500/5" },
                      { id: "extreme", name: "Extreme", icon: <Bomb size={14} />, color: "text-error", border: "border-error", bg: "bg-error/5" },
                    ].map((preset) => {
                      const isSelected = scanAggressiveness === preset.id;
                      return (
                        <button
                          key={preset.id}
                          type="button"
                          onClick={() => setScanAggressiveness(preset.id)}
                          className={`flex flex-col items-center gap-1.5 py-3 border rounded-xl transition-all duration-300 ${
                            isSelected
                              ? `${preset.border} ${preset.bg} shadow-glow`
                              : "border-outline-variant dark:border-[#ffffff10] bg-surface-container dark:bg-[#1A1A24] hover:border-primary/30"
                          }`}
                        >
                          <span className={isSelected ? preset.color : "text-on-surface-variant dark:text-[#8A8A9E]"}>
                            {preset.icon}
                          </span>
                          <span className={`text-[10px] font-bold uppercase tracking-widest font-body ${isSelected ? preset.color : "text-on-surface-variant dark:text-[#8A8A9E]"}`}>
                            {preset.name}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* AI Agent Mode Toggle */}
              <div>
                <label className="block text-[11px] font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-[0.2em] mb-2 font-body">
                  AI Agent Mode
                </label>
                <div className="flex items-center justify-between px-4 py-3 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] rounded-lg">
                  <div className="flex items-center gap-3">
                    <Brain size={18} className={agentMode ? "text-primary" : "text-on-surface-variant/40"} />
                    <div>
                      <div className="text-xs font-medium text-on-surface dark:text-[#F0F0F5]">
                        LLM-Driven Scanning Agent
                      </div>
                      <div className="text-[10px] text-on-surface-variant dark:text-[#8A8A9E]">
                        {agentMode
                          ? "Agent autonomously selects and sequences tools based on recon results"
                          : "Deterministic scan pipeline with predefined tool sequence"}
                      </div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setAgentMode(!agentMode)}
                    className={`relative w-11 h-6 rounded-full transition-all duration-300 ${
                      agentMode ? "bg-primary" : "bg-surface-container-high dark:bg-[#2A2A35]"
                    }`}
                  >
                    <div className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow-md transition-all duration-300 ${
                      agentMode ? "left-[22px]" : "left-0.5"
                    }`} />
                  </button>
                </div>
              </div>

              <button
                type="submit"
                disabled={isLoading || !target}
                className={`w-full flex items-center justify-center gap-2 py-3.5 text-xs font-bold transition-all duration-300 group relative uppercase tracking-[0.2em] rounded-lg font-body ${
                  isLoading
                    ? "bg-transparent text-primary border border-primary/40"
                    : "bg-primary text-on-primary hover:opacity-90 shadow-glow"
                } disabled:opacity-50`}
              >
                {isLoading ? (
                  <span className="flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {progressStep || "Authorizing..."}
                  </span>
                ) : (
                  <>
                    Launch Engagement
                    <ArrowRight size={16} className="group-hover:translate-x-1 transition-transform duration-300" />
                  </>
                )}
              </button>

              {/* Progress Bar */}
              {isLoading && progressStep && (
                <div className="mt-2">
                  <div className="flex items-center justify-between text-[10px] font-mono text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider mb-1">
                    <span className="animate-pulse">{progressStep}</span>
                    <span>Initiating</span>
                  </div>
                  <div className="h-1 w-full bg-surface-container dark:bg-[#1A1A24] rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-full animate-progress"
                      style={{ width: "100%" }}
                    />
                  </div>
                </div>
              )}
            </form>

            <div className="mt-6 flex items-center gap-3 text-[10px] text-on-surface-variant dark:text-[#8A8A9E] font-mono italic uppercase tracking-wider font-bold">
              <AlertTriangle size={14} className="text-primary shrink-0" />
              Authorized operators only — system logging active
            </div>
              </div>
            )}
          </motion.div>

          {/* Live Engagements */}
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="col-span-12 lg:col-span-5 bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-6 transition-all duration-300 hover:border-primary/20 flex flex-col"
          >
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-2">
                <Activity size={18} className="text-primary" />
                <h2 className="text-lg font-headline font-semibold text-on-surface dark:text-[#F0F0F5]">Live Engagements</h2>
              </div>
              <button
                onClick={() => router.push("/engagements/list")}
                className="text-[11px] text-primary hover:underline transition-all duration-300 font-body"
              >
                View All
              </button>
            </div>

            <div className="flex-1 overflow-y-auto max-h-[520px] space-y-3 pr-1">
              {liveLoading && liveEngagements.length === 0 ? (
                <div className="flex items-center justify-center py-10">
                  <Loader2 size={20} className="animate-spin text-primary" />
                </div>
              ) : liveEngagements.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-10 text-on-surface-variant/40 dark:text-[#8A8A9E]/40 gap-3">
                  <Shield size={28} />
                  <p className="text-[11px] font-mono uppercase tracking-widest text-center">No active engagements</p>
                  <p className="text-[10px] text-on-surface-variant/30 dark:text-[#8A8A9E]/30 text-center">Launch a new scan to get started</p>
                </div>
              ) : (
                liveEngagements.map((eng, idx) => {
                  const config = statusConfig[eng.status] || statusConfig.paused;
                  const progress = getScanProgress(eng.status);
                  return (
                    <motion.div
                      key={eng.id}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.3, delay: idx * 0.05 }}
                      whileHover={{ y: -4, transition: { duration: 0.25 } }}
                      className="p-4 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08] rounded-lg transition-all duration-300 hover:border-primary/30 hover:shadow-glow group"
                    >
                      <div className="flex items-start justify-between mb-2">
                        <div className="flex items-center gap-2.5">
                          {eng.scan_type === "repo" ? (
                            <GitBranch size={16} className="text-primary shrink-0" />
                          ) : (
                            <Globe size={16} className="text-primary shrink-0" />
                          )}
                          <div>
                            <p className="text-xs font-mono text-on-surface dark:text-[#F0F0F5] break-all">{eng.target_url}</p>
                            <p className="text-[10px] text-on-surface-variant dark:text-[#8A8A9E] mt-0.5">
                              {new Date(eng.created_at).toLocaleDateString()}
                            </p>
                          </div>
                        </div>
                        <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md ${config.bg} ${config.color}`}>
                          {config.label}
                        </span>
                      </div>

                      {/* Progress */}
                      <div className="mt-3">
                        <div className="flex items-center justify-between text-[9px] font-mono text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider mb-1">
                          <span>Progress</span>
                          <span>{progress}%</span>
                        </div>
                        <div className="h-1.5 w-full bg-surface-container-high dark:bg-[#1A1A24] rounded-full overflow-hidden">
                          <motion.div
                            className="h-full bg-primary rounded-full"
                            initial={{ width: 0 }}
                            animate={{ width: `${progress}%` }}
                            transition={{ duration: 0.6, ease: "easeOut" }}
                          />
                        </div>
                      </div>

                      {/* Stats & Actions */}
                      <div className="flex items-center justify-between mt-3 pt-3 border-t border-outline-variant dark:border-[#ffffff08]">
                        <div className="flex gap-3 text-[10px] font-mono">
                          <span className="text-on-surface-variant dark:text-[#8A8A9E]">{eng.findings_count} findings</span>
                          {eng.critical_count > 0 && (
                            <span className="text-error">{eng.critical_count} critical</span>
                          )}
                        </div>
                        <div className="flex gap-1">
                          <button
                            onClick={() => router.push(`/dashboard?engagement=${eng.id}`)}
                            className="p-1.5 text-on-surface-variant dark:text-[#8A8A9E] hover:text-primary transition-all duration-300 rounded-md hover:bg-primary/5"
                            title="Monitor"
                          >
                            <Eye size={14} />
                          </button>
                          {eng.status !== "complete" && eng.status !== "failed" && eng.status !== "paused" && (
                            <button
                              onClick={() => handleStop(eng.id)}
                              disabled={stoppingId === eng.id}
                              className="p-1.5 text-on-surface-variant dark:text-[#8A8A9E] hover:text-error transition-all duration-300 rounded-md hover:bg-error/5 disabled:opacity-40"
                              title="Stop scan"
                            >
                              {stoppingId === eng.id ? (
                                <Loader2 size={14} className="animate-spin" />
                              ) : (
                                <StopCircle size={14} />
                              )}
                            </button>
                          )}
                          {["complete", "failed", "paused"].includes(eng.status) && (
                            <button
                              onClick={() => handleRescan(eng.id)}
                              disabled={rescannings.has(eng.id)}
                              className="p-1.5 text-on-surface-variant dark:text-[#8A8A9E] hover:text-primary transition-all duration-300 rounded-md hover:bg-primary/5 disabled:opacity-40"
                              title="Rescan"
                            >
                              {rescannings.has(eng.id) ? (
                                <Loader2 size={14} className="animate-spin" />
                              ) : (
                                <RefreshCw size={14} />
                              )}
                            </button>
                          )}
                          <button
                            onClick={() => handleDelete(eng.id)}
                            className="p-1.5 text-on-surface-variant dark:text-[#8A8A9E] hover:text-error transition-all duration-300 rounded-md hover:bg-error/5"
                            title="Delete"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </div>
                    </motion.div>
                  );
                })
              )}
            </div>
          </motion.div>
        </div>

        {/* ── Meta Info ── */}
        <ScrollReveal direction="up" delay={0.15}>
          <StaggerContainer className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-6" staggerDelay={0.06}>
            <StaggerItem>
              <motion.div whileHover={{ y: -3, transition: { duration: 0.25 } }} className="bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-4 transition-all duration-300 hover:border-primary/20">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center">
                    <Server size={18} className="text-primary" />
                  </div>
                  <div>
                    <div className="text-[10px] font-body text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider">VPC Tunneling</div>
                    <div className="text-sm font-body text-on-surface dark:text-[#F0F0F5] font-medium">Active • us-east-1</div>
                  </div>
                </div>
              </motion.div>
            </StaggerItem>
            <StaggerItem>
              <motion.div whileHover={{ y: -3, transition: { duration: 0.25 } }} className="bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-4 transition-all duration-300 hover:border-primary/20">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center">
                    <Cpu size={18} className="text-primary" />
                  </div>
                  <div>
                    <div className="text-[10px] font-body text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider">Model Version</div>
                    <div className="text-sm font-body text-on-surface dark:text-[#F0F0F5] font-medium">Argus v1.0.0</div>
                  </div>
                </div>
              </motion.div>
            </StaggerItem>
            <StaggerItem>
              <motion.div whileHover={{ y: -3, transition: { duration: 0.25 } }} className="bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-4 transition-all duration-300 hover:border-primary/20">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center">
                    <Shield size={18} className="text-primary" />
                  </div>
                  <div>
                    <div className="text-[10px] font-body text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider">Total Scans</div>
                    <div className="text-sm font-body text-on-surface dark:text-[#F0F0F5] font-medium">{liveEngagements.length} engagements</div>
                  </div>
                </div>
              </motion.div>
            </StaggerItem>
            <StaggerItem>
              <motion.div whileHover={{ y: -3, transition: { duration: 0.25 } }} className="bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-4 transition-all duration-300 hover:border-primary/20">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center">
                    <Activity size={18} className="text-primary" />
                  </div>
                  <div>
                    <div className="text-[10px] font-body text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider">Active Scans</div>
                    <div className="text-sm font-body text-on-surface dark:text-[#F0F0F5] font-medium">
                      {liveEngagements.filter((e) => ["scanning", "analyzing", "recon", "reporting"].includes(e.status)).length} running
                    </div>
                  </div>
                </div>
              </motion.div>
            </StaggerItem>
          </StaggerContainer>
        </ScrollReveal>

        {/* ── Analytics Preview ── */}
        <ScrollReveal direction="up" delay={0.15}>
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.4 }}
            whileHover={{ y: -3, transition: { duration: 0.25 } }}
            className="mt-6 bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-6 transition-all duration-300 hover:border-primary/20"
          >
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between mb-6 gap-4">
            <div className="flex items-center gap-2">
              <BarChart3 size={18} className="text-primary" />
              <h3 className="text-lg font-headline font-semibold text-on-surface dark:text-[#F0F0F5]">Engagement Analytics</h3>
            </div>
            <button
              onClick={() => router.push("/reports")}
              className="flex items-center gap-2 px-4 py-2 bg-primary text-on-primary text-xs font-bold uppercase tracking-widest hover:opacity-90 transition-all duration-300 shadow-glow rounded-lg font-body"
            >
              View Reports
              <ArrowRight size={14} />
            </button>
          </div>

          {analyticsData.length > 0 ? (
            <div className="h-[220px] w-full">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={analyticsData} barCategoryGap="20%">
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(122, 116, 137, 0.15)" />
                  <XAxis
                    dataKey="name"
                    tick={{ fontSize: 11, fill: "#7A7489" }}
                    axisLine={{ stroke: "rgba(122, 116, 137, 0.2)" }}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: "#7A7489" }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#FFFFFF",
                      border: "1px solid #CAC3DA",
                      borderRadius: "8px",
                      fontSize: "12px",
                    }}
                    cursor={{ fill: "rgba(103, 32, 255, 0.05)" }}
                  />
                  <Bar dataKey="findings" fill="#6720FF" radius={[4, 4, 0, 0]} name="Findings" />
                  <Bar dataKey="critical" fill="#BA1A1A" radius={[4, 4, 0, 0]} name="Critical" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="h-[220px] flex flex-col items-center justify-center text-on-surface-variant/40 dark:text-[#8A8A9E]/40 gap-3">
              <BarChart3 size={28} />
              <p className="text-[11px] font-mono uppercase tracking-widest">No analytics data available</p>
            </div>
          )}
          </motion.div>
        </ScrollReveal>
      </div>
    </div>
  );
}
