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
  Save,
  FileText,
  X,
  CheckCircle,
  Sword,
  Code2,
  Copy,
  TrendingUp,
  TrendingDown,
  Minus,
} from "lucide-react";
import { useEngagementEvents } from "@/lib/use-engagement-events";
import type { AgentDecisionEvent } from "@/lib/websocket-events";
import AuthWizard from "@/components/ui-custom/AuthWizard";

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
  agent_mode?: boolean;
  scan_mode?: string;
  bug_bounty_mode?: boolean;
  auth_config?: Record<string, unknown> | null;
  dual_auth_config?: Record<string, unknown> | null;
  priority_vuln_classes?: string[];
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
  const [showSaveTemplate, setShowSaveTemplate] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [templateDescription, setTemplateDescription] = useState("");
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [attackPaths, setAttackPaths] = useState<Array<{
    id: string;
    risk_score: number;
    path_nodes?: { nodes: Array<{ type: string; data: Record<string, unknown> }> } | null;
    chain_exploit_script: Record<string, unknown> | null;
  }>>([]);
  const [attackPathsLoading, setAttackPathsLoading] = useState(true);
  const [showAuthWizard, setShowAuthWizard] = useState(false);
  const [updatingAuth, setUpdatingAuth] = useState(false);
  const [linkedRules, setLinkedRules] = useState<Array<{
    id: string; name: string; severity: string; category: string; linked_at: string;
  }>>([]);
  const [showRuleSelector, setShowRuleSelector] = useState(false);
  const [availableRules, setAvailableRules] = useState<Array<{
    id: string; name: string; severity: string; category: string;
  }>>([]);
  const [selectedRuleIds, setSelectedRuleIds] = useState<Set<string>>(new Set());
  const [linkingRules, setLinkingRules] = useState(false);

  // Real-time events for agent reasoning feed and posture updates
  const { events, postureScore, postureTrend } = useEngagementEvents({
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

  const fetchLinkedRules = useCallback(async () => {
    try {
      const res = await fetch(`/api/engagement/${engagementId}/rules`);
      if (res.ok) {
        const data = await res.json();
        setLinkedRules(data.rules || []);
      }
    } catch { /* non-critical */ }
  }, [engagementId]);

  const fetchAvailableRules = useCallback(async () => {
    try {
      const res = await fetch("/api/rules?status=active&limit=200");
      if (res.ok) {
        const data = await res.json();
        setAvailableRules(data.rules || []);
      }
    } catch { /* non-critical */ }
  }, []);

  const fetchAttackPaths = useCallback(async () => {
    try {
      const res = await fetch(`/api/engagement/${engagementId}/attack-paths`);
      if (res.ok) {
        const data = await res.json();
        setAttackPaths((data.attack_paths || []).filter(
          (p: { risk_score: number }) => parseFloat(String(p.risk_score)) >= 5.0
        ));
      }
    } catch { /* non-critical */ }
    finally { setAttackPathsLoading(false); }
  }, [engagementId]);

  useEffect(() => {
    if (status !== "authenticated" || !engagementId) return;
    fetchEngagement();
    fetchFindings();
    fetchTimeline();
    fetchAttackPaths();
    fetchLinkedRules();
  }, [status, engagementId, fetchEngagement, fetchFindings, fetchTimeline, fetchAttackPaths, fetchLinkedRules]);

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

  const handleSaveTemplate = async () => {
    if (!templateName.trim()) return;
    setSavingTemplate(true);
    try {
      const authCfg = engagement?.auth_config;
      const dualAuthCfg = engagement?.dual_auth_config;
      const config: Record<string, unknown> = {
        target_url_pattern: engagement?.target_url || "",
        scan_type: engagement?.scan_type || "url",
        aggressiveness: engagement?.scan_aggressiveness || "default",
        agent_mode: engagement?.agent_mode || false,
        scan_mode: engagement?.scan_mode || "agent",
        bug_bounty_mode: engagement?.bug_bounty_mode || false,
        priority_vuln_classes: engagement?.priority_vuln_classes || [],
      };
      // Save auth config type if configured (strip credentials for security)
      if (authCfg && typeof authCfg === "object" && authCfg.type) {
        config.auth_config_type = authCfg.type;
      }
      // Save dual-auth config type if configured (strip credentials for security)
      if (dualAuthCfg && typeof dualAuthCfg === "object" && dualAuthCfg.type) {
        config.dual_auth_config_type = dualAuthCfg.type;
      }
      const res = await fetch("/api/templates", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: templateName.trim(),
          description: templateDescription.trim(),
          config,
        }),
      });
      if (res.ok) {
        showToast("success", "Template saved");
        setShowSaveTemplate(false);
        setTemplateName("");
        setTemplateDescription("");
      } else {
        const data = await res.json().catch(() => ({}));
        showToast("error", data.error || "Failed to save template");
      }
    } catch {
      showToast("error", "Failed to save template");
    } finally {
      setSavingTemplate(false);
    }
  };

  const handleUpdateAuth = async (config: Record<string, unknown> | null, dualConfig: Record<string, unknown> | null) => {
    setUpdatingAuth(true);
    try {
      const res = await fetch(`/api/engagement/${engagementId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          auth_config: config,
          dual_auth_config: dualConfig,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setEngagement(data.engagement);
        showToast("success", "Auth configuration updated");
        setShowAuthWizard(false);
      } else {
        const err = await res.json().catch(() => ({}));
        showToast("error", err.error || "Failed to update auth config");
      }
    } catch {
      showToast("error", "Failed to update auth config");
    } finally {
      setUpdatingAuth(false);
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
              <>
                <button
                  onClick={() => router.push(`/engagements?clone=${engagement.id}`)}
                  className="flex items-center gap-2 px-4 py-2 bg-primary/10 border border-primary/30 text-primary text-[10px] font-bold uppercase tracking-widest rounded-lg hover:bg-primary/20 transition-all"
                >
                  <Copy size={12} />
                  Clone
                </button>
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
                <button
                  onClick={() => setShowSaveTemplate(true)}
                  className="flex items-center gap-2 px-4 py-2 bg-green-500/10 border border-green-500/30 text-green-500 text-[10px] font-bold uppercase tracking-widest rounded-lg hover:bg-green-500/20 transition-all"
                >
                  <Save size={12} />
                  Save as Template
                </button>
              </>
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

      {/* Save as Template Modal */}
      <AnimatePresence>
      {showSaveTemplate && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          onClick={() => setShowSaveTemplate(false)}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            onClick={(e) => e.stopPropagation()}
            className="bg-surface dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-6 w-full max-w-md mx-4 shadow-2xl"
          >
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <FileText size={16} className="text-primary" />
                <h3 className="text-sm font-headline font-semibold text-on-surface dark:text-[#F0F0F5]">Save as Template</h3>
              </div>
              <button
                onClick={() => setShowSaveTemplate(false)}
                className="p-1.5 rounded-lg hover:bg-surface-container dark:hover:bg-[#1A1A24] text-on-surface-variant transition-colors"
              >
                <X size={14} />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-1.5 font-body">
                  Template Name
                </label>
                <input
                  type="text"
                  value={templateName}
                  onChange={(e) => setTemplateName(e.target.value)}
                  placeholder="e.g. Quarterly Banking App Scan"
                  className="w-full px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] rounded-lg text-xs font-mono text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary transition-all duration-200"
                  autoFocus
                />
              </div>

              <div>
                <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-[0.2em] mb-1.5 font-body">
                  Description (optional)
                </label>
                <textarea
                  value={templateDescription}
                  onChange={(e) => setTemplateDescription(e.target.value)}
                  placeholder="What is this template for?"
                  rows={2}
                  className="w-full px-3 py-2.5 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] rounded-lg text-xs font-mono text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary transition-all duration-200 resize-none"
                />
              </div>

              <div className="p-3 rounded-lg bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08]">
                <span className="text-[9px] font-bold text-on-surface-variant uppercase tracking-wider">Config will save:</span>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  <span className="text-[9px] font-mono bg-primary/10 text-primary px-1.5 py-0.5 rounded">{engagement?.scan_type || "url"}</span>
                  <span className="text-[9px] font-mono bg-primary/10 text-primary px-1.5 py-0.5 rounded">{engagement?.scan_aggressiveness || "default"}</span>
                  {engagement?.agent_mode && (
                    <span className="text-[9px] font-mono bg-amber-500/10 text-amber-500 px-1.5 py-0.5 rounded">AI Agent</span>
                  )}
                  <span className="text-[9px] font-mono bg-primary/10 text-primary px-1.5 py-0.5 rounded">{engagement?.scan_mode || "agent"} mode</span>
                  {Boolean((engagement?.auth_config as Record<string, string | undefined> | null)?.type) && (
                    <span className="text-[9px] font-mono bg-green-500/10 text-green-500 px-1.5 py-0.5 rounded">
                      auth: {String((engagement?.auth_config as Record<string, string>)?.type)}
                      {(engagement?.dual_auth_config as Record<string, string | undefined> | null)?.type ? " + dual" : ""}
                    </span>
                  )}
                </div>
                <p className="text-[9px] text-on-surface-variant/60 mt-2">
                  Target URL, scan type, aggressiveness, agent mode, scan mode, auth config, and dual-auth config
                </p>
              </div>

              <div className="flex gap-2 pt-2">
                <button
                  onClick={() => setShowSaveTemplate(false)}
                  className="flex-1 py-2.5 border border-outline-variant dark:border-[#ffffff10] text-on-surface-variant text-[10px] font-bold uppercase tracking-wider rounded-lg hover:border-primary/30 transition-all"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSaveTemplate}
                  disabled={savingTemplate || !templateName.trim()}
                  className="flex-1 flex items-center justify-center gap-2 py-2.5 bg-primary text-on-primary text-[10px] font-bold uppercase tracking-wider rounded-lg hover:opacity-90 transition-all disabled:opacity-50"
                >
                  {savingTemplate ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <CheckCircle size={12} />
                  )}
                  Save Template
                </button>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
      </AnimatePresence>

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
                <span className="text-[10px] font-mono text-on-surface-variant block">Priority Vuln Classes</span>
                <div className="flex items-center gap-1 mt-0.5 flex-wrap">
                  {engagement?.priority_vuln_classes && engagement.priority_vuln_classes.length > 0 ? (
                    engagement.priority_vuln_classes.map((cls) => (
                      <span key={cls} className="text-[9px] font-mono bg-primary/10 text-primary px-1.5 py-0.5 rounded border border-primary/20">
                        {cls}
                      </span>
                    ))
                  ) : (
                    <span className="text-[10px] font-mono text-on-surface-variant/60">None</span>
                  )}
                </div>
              </div>
              <div>
                <span className="text-[10px] font-mono text-on-surface-variant block">Auth Config</span>
                <div className="flex items-center gap-2 mt-0.5">
                  {Boolean((engagement?.auth_config as Record<string, string | undefined> | null)?.type) ? (
                    <span className="text-[10px] font-mono bg-green-500/10 text-green-500 px-1.5 py-0.5 rounded border border-green-500/20">
                      {String((engagement?.auth_config as Record<string, string>)?.type)}
                      {(engagement?.dual_auth_config as Record<string, string | undefined> | null)?.type ? " + dual" : ""}
                    </span>
                  ) : (
                    <span className="text-[10px] font-mono text-on-surface-variant/60">None</span>
                  )}
                  <button
                    onClick={() => setShowAuthWizard(true)}
                    disabled={updatingAuth}
                    className="text-[9px] font-mono text-primary hover:text-primary/80 transition-colors disabled:opacity-50"
                  >
                    {updatingAuth ? "Saving..." : "Edit"}
                  </button>
                </div>
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
              {postureScore != null && (
                <div className="col-span-2 bg-surface-container dark:bg-[#1A1A24] rounded-lg p-3 border border-outline-variant dark:border-[#ffffff08]">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-[10px] font-mono text-on-surface-variant uppercase tracking-wider">Posture Score</div>
                      <div className="text-xl font-headline font-bold text-on-surface mt-1">
                        {Math.round(postureScore)}
                        <span className="text-sm font-mono ml-2 text-on-surface-variant">/ 100</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {postureTrend === "improving" && (
                        <span className="flex items-center gap-1 text-[10px] font-mono text-green-500 bg-green-500/10 px-2 py-1 rounded border border-green-500/20">
                          <TrendingUp size={12} />
                          Improving
                        </span>
                      )}
                      {postureTrend === "declining" && (
                        <span className="flex items-center gap-1 text-[10px] font-mono text-error bg-error/10 px-2 py-1 rounded border border-error/20">
                          <TrendingDown size={12} />
                          Declining
                        </span>
                      )}
                      {postureTrend === "stable" && (
                        <span className="flex items-center gap-1 text-[10px] font-mono text-on-surface-variant bg-surface-container-high px-2 py-1 rounded border border-outline-variant">
                          <Minus size={12} />
                          Stable
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="mt-2 w-full bg-surface-container-high rounded-full h-1.5 overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-1000 ease-out"
                      style={{
                        width: `${postureScore}%`,
                        background: postureScore >= 80
                          ? "linear-gradient(90deg, #00FF88, #00CC6A)"
                          : postureScore >= 50
                            ? "linear-gradient(90deg, #FF8800, #FFAA33)"
                            : "linear-gradient(90deg, #FF4444, #FF6644)",
                      }}
                    />
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        </div>

        {/* Custom Rules */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-5"
        >
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest font-headline">
              Custom Rules
            </h3>
            <button
              onClick={() => {
                fetchAvailableRules();
                setShowRuleSelector(!showRuleSelector);
              }}
              className="text-[9px] font-mono text-primary hover:text-primary/80 transition-colors"
            >
              {showRuleSelector ? "Cancel" : linkedRules.length > 0 ? "Manage" : "Link Rules"}
            </button>
          </div>

          {linkedRules.length === 0 && !showRuleSelector ? (
            <p className="text-[10px] font-mono text-on-surface-variant/40">
              No custom rules linked to this engagement
            </p>
          ) : (
            <div className="space-y-2">
              {linkedRules.map((rule) => (
                <div
                  key={rule.id}
                  className="flex items-center justify-between px-3 py-2 bg-surface-container dark:bg-[#1A1A24] rounded-lg border border-outline-variant dark:border-[#ffffff08]"
                >
                  <div className="min-w-0 flex-1">
                    <span className="text-xs font-mono text-on-surface truncate block">
                      {rule.name}
                    </span>
                    <span className={`text-[9px] font-mono ${rule.severity === "CRITICAL" ? "text-error" : rule.severity === "HIGH" ? "text-orange-500" : "text-on-surface-variant"}`}>
                      {rule.severity}
                    </span>
                  </div>
                  <button
                    onClick={async () => {
                      const res = await fetch(`/api/engagement/${engagementId}/rules`, {
                        method: "DELETE",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ ruleIds: [rule.id] }),
                      });
                      if (res.ok) fetchLinkedRules();
                    }}
                    className="text-[9px] font-mono text-error/60 hover:text-error transition-colors shrink-0 ml-2"
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Rule Selector Panel */}
          {showRuleSelector && (
            <div className="mt-3 space-y-2">
              <div className="max-h-[200px] overflow-y-auto space-y-1 pr-1">
                {availableRules
                  .filter((r) => !linkedRules.find((lr) => lr.id === r.id))
                  .map((rule) => (
                    <label
                      key={rule.id}
                      className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-surface-container-high dark:hover:bg-[#2A2A35] cursor-pointer transition-colors"
                    >
                      <input
                        type="checkbox"
                        checked={selectedRuleIds.has(rule.id)}
                        onChange={() => {
                          const next = new Set(selectedRuleIds);
                          if (next.has(rule.id)) next.delete(rule.id);
                          else next.add(rule.id);
                          setSelectedRuleIds(next);
                        }}
                        className="rounded border-outline-variant"
                      />
                      <span className="text-[11px] font-mono text-on-surface truncate flex-1">
                        {rule.name}
                      </span>
                      <span className={`text-[9px] font-mono shrink-0 ${rule.severity === "CRITICAL" ? "text-error" : rule.severity === "HIGH" ? "text-orange-500" : "text-on-surface-variant"}`}>
                        {rule.severity}
                      </span>
                    </label>
                  ))}
                {availableRules.filter((r) => !linkedRules.find((lr) => lr.id === r.id)).length === 0 && (
                  <p className="text-[10px] font-mono text-on-surface-variant/40 text-center py-3">
                    No additional rules available
                  </p>
                )}
              </div>
              <button
                disabled={selectedRuleIds.size === 0 || linkingRules}
                onClick={async () => {
                  setLinkingRules(true);
                  try {
                    const res = await fetch(`/api/engagement/${engagementId}/rules`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ ruleIds: Array.from(selectedRuleIds) }),
                    });
                    if (res.ok) {
                      setSelectedRuleIds(new Set());
                      fetchLinkedRules();
                    }
                  } finally {
                    setLinkingRules(false);
                  }
                }}
                className="w-full py-2 bg-primary/10 text-primary border border-primary/20 rounded-lg text-[10px] font-mono hover:bg-primary/20 transition-colors disabled:opacity-50"
              >
                {linkingRules ? "Linking..." : `Link Selected (${selectedRuleIds.size})`}
              </button>
            </div>
          )}
        </motion.div>

        {/* Auth Wizard — inline when active */}
        {showAuthWizard && engagement && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="col-span-12 lg:col-span-4"
          >
            <div className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-5">
              <AuthWizard
                targetUrl={engagement.target_url}
                onComplete={(config) => {
                  const rawConfig = config as unknown as Record<string, unknown>;
                  const dualCfg = rawConfig.dualConfig as Record<string, unknown> | undefined;
                  const { dualConfig: _, ...mainConfig } = rawConfig;
                  handleUpdateAuth(mainConfig, dualCfg || null);
                }}
                onSkip={() => {
                  setShowAuthWizard(false);
                }}
              />
            </div>
          </motion.div>
        )}

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

          {/* Attack Chains — shown for completed/analyzing engagements */}
          {engagement && ["analyzing", "complete", "reporting"].includes(engagement.status) && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.25 }}
              className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-5"
            >
              <div className="flex items-center gap-2 mb-4">
                <Sword size={14} className="text-primary" />
                <h3 className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest font-headline">
                  Attack Chains
                </h3>
                {attackPaths.length > 0 && (
                  <span className="text-[9px] font-mono bg-error/10 text-error px-1.5 py-0.5 rounded ml-auto">
                    {attackPaths.filter((p) => p.chain_exploit_script).length} verified
                  </span>
                )}
              </div>

              {attackPathsLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 size={16} className="animate-spin text-primary" />
                </div>
              ) : attackPaths.length === 0 ? (
                <div className="py-8 text-center">
                  <Shield size={24} className="mx-auto text-on-surface-variant/20 mb-2" />
                  <p className="text-[11px] font-mono text-on-surface-variant/40 uppercase tracking-widest">
                    No high-risk attack chains detected
                  </p>
                </div>
              ) : (
                <div className="space-y-3 max-h-[500px] overflow-y-auto pr-1">
                  {attackPaths.map((path) => {
                    const vulnNodes = (path.path_nodes?.nodes || []).filter(
                      (n: { type: string }) => n.type === "vulnerability"
                    );
                    const chainName = vulnNodes
                      .map((n: { data: Record<string, unknown> }) => String(n.data?.type || "UNKNOWN").replace(/_/g, " "))
                      .join(" → ");
                    const riskColor = path.risk_score >= 8 ? "text-error" : path.risk_score >= 6 ? "text-orange-500" : "text-amber-500";
                    const exploitScript = path.chain_exploit_script as Record<string, unknown> | null;

                    return (
                      <div
                        key={path.id}
                        className="p-4 rounded-lg bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08]"
                      >
                        <div className="flex items-start justify-between mb-2">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-mono text-on-surface dark:text-[#F0F0F5] truncate">
                                {chainName || "Unknown Chain"}
                              </span>
                              <span className={`text-[9px] font-bold uppercase ${riskColor}`}>
                                CVSS {path.risk_score}
                              </span>
                            </div>
                            <div className="flex flex-wrap gap-1.5 mt-1.5">
                              {vulnNodes.map((n: { data: Record<string, unknown> }, i: number) => (
                                <span key={i} className="text-[9px] font-mono text-primary bg-primary/10 px-1.5 py-0.5 rounded">
                                  {String(n.data?.type || "?").replace(/_/g, " ")}
                                </span>
                              ))}
                            </div>
                          </div>
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded ${riskColor.replace("text-", "bg-")}/10`}>
                            {path.risk_score}
                          </span>
                        </div>

                        {/* Exploit Script Section */}
                        {exploitScript && (
                          <div className="mt-3 pt-3 border-t border-outline-variant dark:border-[#ffffff08]">
                            <div className="flex items-center gap-2 mb-2">
                              <Code2 size={11} className="text-green-500" />
                              <span className="text-[9px] font-bold text-green-500 uppercase tracking-wider">
                                Chain Exploit Script
                              </span>
                            </div>
                            <pre className="text-[9px] font-mono leading-relaxed bg-surface-container-high dark:bg-[#2A2A35] rounded-lg p-3 overflow-x-auto max-h-48 overflow-y-auto text-on-surface-variant dark:text-[#B0B0C0] whitespace-pre-wrap">
                              {typeof exploitScript.script === "string"
                                ? exploitScript.script
                                : typeof exploitScript === "string"
                                  ? exploitScript
                                  : JSON.stringify(exploitScript, null, 2)}
                            </pre>
                            {Boolean((exploitScript as Record<string, unknown>).impact_summary) && (
                              <p className="text-[9px] text-on-surface-variant/60 mt-2 italic">
                                Impact: {String((exploitScript as Record<string, unknown>).impact_summary)}
                              </p>
                            )}
                          </div>
                        )}

                        {/* Generate Button for paths without scripts */}
                        {!exploitScript && engagement?.status === "complete" && (
                          <div className="mt-3 pt-3 border-t border-outline-variant dark:border-[#ffffff08]">
                            <button
                              onClick={async () => {
                                try {
                                  const res = await fetch(`/api/engagement/${engagementId}/generate-chain-exploits`, {
                                    method: "POST",
                                  });
                                  if (!res.ok) {
                                    const err = await res.json();
                                    console.error("Failed to generate chain exploits:", err);
                                    return;
                                  }
                                  const data = await res.json();
                                  console.log("Chain exploit generation queued:", data);
                                  // Refresh the page to show updated paths
                                  window.location.reload();
                                } catch (err) {
                                  console.error("Failed to generate chain exploits:", err);
                                }
                              }}
                              className="text-[9px] font-mono text-primary bg-primary/10 border border-primary/20 px-2 py-1 rounded hover:bg-primary/20 transition-colors"
                            >
                              Generate Exploit Script
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </motion.div>
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
