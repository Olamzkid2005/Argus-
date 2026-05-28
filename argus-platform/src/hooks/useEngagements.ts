"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { log } from "@/lib/logger";

export interface Engagement {
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

export const statusConfig: Record<string, { color: string; bg: string; label: string }> = {
  created: { color: "text-blue-500", bg: "bg-blue-500/10", label: "Created" },
  recon: { color: "text-amber-500", bg: "bg-amber-500/10", label: "Recon" },
  scanning: { color: "text-primary", bg: "bg-primary/10", label: "Scanning" },
  analyzing: { color: "text-cyan-500", bg: "bg-cyan-500/10", label: "Analyzing" },
  reporting: { color: "text-pink-500", bg: "bg-pink-500/10", label: "Reporting" },
  complete: { color: "text-green-500", bg: "bg-green-500/10", label: "Complete" },
  failed: { color: "text-error", bg: "bg-error/10", label: "Failed" },
  paused: { color: "text-on-surface-variant", bg: "bg-surface-container", label: "Paused" },
};

export function useEngagements() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data: session, status } = useSession();
  const { showToast } = useToast();

  // Form state
  const [scanType, setScanType] = useState<"url" | "repo">("url");
  const [target, setTarget] = useState("");
  const [scanAggressiveness, setScanAggressiveness] = useState("default");
  const [agentMode, setAgentMode] = useState(false);
  const [scanMode, setScanMode] = useState<"agent" | "swarm">("agent");
  const [bugBounty, setBugBounty] = useState(false);
  const [priorityVulnClasses, setPriorityVulnClasses] = useState<string[]>([]);

  // UI state
  const [isLoading, setIsLoading] = useState(false);
  const [progressStep, setProgressStep] = useState("");
  const [error, setError] = useState("");
  const [stoppingId, setStoppingId] = useState<string | null>(null);
  const [rescannings, setRescannings] = useState<Set<string>>(new Set());
  const [showAllHistory, setShowAllHistory] = useState(false);
  const [settingsLoading, setSettingsLoading] = useState(true);

  // Template variable substitution state
  const [templateVariables, setTemplateVariables] = useState<Record<string, string>>({});
  const [showVariablePrompt, setShowVariablePrompt] = useState(false);
  const [pendingTemplateConfig, setPendingTemplateConfig] = useState<Record<string, unknown> | null>(null);

  // Natural Language scan config state
  const [configMode, setConfigMode] = useState<"standard" | "nl">("standard");
  const [nlIntent, setNlIntent] = useState("");
  const [nlLoading, setNlLoading] = useState(false);
  const [nlResult, setNlResult] = useState<Record<string, string | boolean | string[]> | null>(null);
  const [nlError, setNlError] = useState("");
  const [nlIsFallback, setNlIsFallback] = useState(false);

  // Auth Wizard state
  const [authConfig, setAuthConfig] = useState<Record<string, unknown> | null>(null);
  const [dualAuthConfig, setDualAuthConfig] = useState<Record<string, unknown> | null>(null);
  const [showAuthWizard, setShowAuthWizard] = useState(false);

  // Engagement Templates state
  const [templates, setTemplates] = useState<Array<{ id: string; name: string; description: string; config: Record<string, unknown> }>>([]);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");

  const { history, addToHistory, removeFromHistory, clearHistory } = useURLHistory();

  // Live engagements state
  const [liveEngagements, setLiveEngagements] = useState<Engagement[]>([]);
  const [liveLoading, setLiveLoading] = useState(false);

  // Load engagement templates
  useEffect(() => {
    if (status !== "authenticated") return;
    const fetchTemplates = async () => {
      try {
        const res = await fetch("/api/templates");
        if (res.ok) {
          const data = await res.json();
          setTemplates(data.templates || []);
        }
      } catch {
        // non-critical
      } finally {
        setTemplatesLoading(false);
      }
    };
    fetchTemplates();
  }, [status]);

  // Handle clone parameter from URL
  useEffect(() => {
    if (status !== "authenticated") return;
    const cloneId = searchParams.get("clone");
    if (!cloneId) return;

    const fetchCloneEngagement = async () => {
      try {
        const res = await fetch(`/api/engagement/${cloneId}`);
        if (!res.ok) {
          showToast("error", "Failed to load engagement for cloning");
          return;
        }
        const data = await res.json();
        const eng = data.engagement;
        if (!eng) return;

        if (eng.target_url) setTarget(eng.target_url);
        if (eng.scan_type) setScanType(eng.scan_type as "url" | "repo");
        if (eng.scan_aggressiveness) setScanAggressiveness(eng.scan_aggressiveness);
        if (eng.agent_mode !== undefined) setAgentMode(Boolean(eng.agent_mode));
        if (eng.scan_mode) setScanMode(eng.scan_mode as "agent" | "swarm");
        if (eng.bug_bounty_mode) setBugBounty(Boolean(eng.bug_bounty_mode));
        if (eng.auth_config?.type) {
          setShowAuthWizard(true);
        }
        showToast("success", `Cloning "${eng.target_url}" — adjust settings and launch`);
      } catch {
        showToast("error", "Failed to load engagement for cloning");
      }
    };
    fetchCloneEngagement();
  }, [status, searchParams, showToast]);

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
          authConfig: nlResult.auth_config || null,
          authorization: "AUTHORIZED OPERATIONAL SCAN",
          authorizedScope: {},
          scanMode: "agent",
          bugBounty: false,
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
          scanMode: scanMode,
          bugBounty: bugBounty,
          authConfig: authConfig,
          dualAuthConfig: dualAuthConfig,
          priorityVulnClasses: priorityVulnClasses,
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
    } catch {
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
    const order = ["created", "recon", "scanning", "analyzing", "reporting", "complete"];
    const idx = order.indexOf(status);
    if (idx === -1) return 0;
    return Math.round(((idx + 1) / order.length) * 100);
  };

  return {
    // Session
    session, status,

    // Form state
    scanType, setScanType,
    target, setTarget,
    scanAggressiveness, setScanAggressiveness,
    agentMode, setAgentMode,
    scanMode, setScanMode,
    bugBounty, setBugBounty,
    priorityVulnClasses, setPriorityVulnClasses,

    // UI state
    isLoading, setIsLoading,
    progressStep, setProgressStep,
    error, setError,
    stoppingId, setStoppingId,
    rescannings, setRescannings,
    showAllHistory, setShowAllHistory,
    settingsLoading, setSettingsLoading,

    // Template state
    templateVariables, setTemplateVariables,
    showVariablePrompt, setShowVariablePrompt,
    pendingTemplateConfig, setPendingTemplateConfig,

    // NL state
    configMode, setConfigMode,
    nlIntent, setNlIntent,
    nlLoading, setNlLoading,
    nlResult, setNlResult,
    nlError, setNlError,
    nlIsFallback, setNlIsFallback,

    // Auth wizard state
    authConfig, setAuthConfig,
    dualAuthConfig, setDualAuthConfig,
    showAuthWizard, setShowAuthWizard,

    // Templates
    templates, setTemplates,
    templatesLoading, setTemplatesLoading,
    selectedTemplateId, setSelectedTemplateId,

    // URL history
    history, addToHistory, removeFromHistory, clearHistory,

    // Live engagements
    liveEngagements, setLiveEngagements,
    liveLoading, setLiveLoading,

    // Computed
    analyticsData,
    getDomain,

    // Handlers
    handleSubmit,
    handleDelete,
    handleStop,
    handleRescan,
    handleParseIntent,
    handleNlStartScan,
    handleNlEditDetails,
    getScanProgress,
  };
}
