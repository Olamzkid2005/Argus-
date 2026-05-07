"use client";

import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { useMobileDetect } from "@/hooks/useMobileDetect";
import { motion, AnimatePresence } from "framer-motion";
import { log } from "@/lib/logger";
import {
  Search,
  Filter,
  ChevronDown,
  Bug,
  AlertTriangle,
  Shield,
  Copy,
  Check,
  Loader2,
  Trash2,
  CheckCircle2,
  Brain,
  Sparkles,
  Zap,
  Link2,
  Sword,
  Target,
  X,
  ChevronRight,
  UserCheck,
  Wrench,
  Code2,
} from "lucide-react";
import ScannerReveal from "@/components/effects/ScannerReveal";
import { AIStatusBadge } from "@/components/ui-custom/AIStatus";
import { MarkdownRenderer } from "@/components/ui-custom/MarkdownRenderer";
import { ScrollReveal } from "@/components/animations/ScrollReveal";
import { StaggerContainer, StaggerItem } from "@/components/animations/StaggerContainer";
import SecurityRating from "@/components/security/SecurityRating";


// ── Types ──
interface Finding {
  id: string;
  engagement_id: string;
  target_url?: string;
  type: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
  endpoint: string;
  source_tool: string;
  verified: boolean;
  confidence?: number;
  created_at: string;
  evidence?: any;
}

interface Engagement {
  id: string;
  target_url: string;
  status: string;
  findings_count: number;
  created_at: string;
}

interface Explanations {
  [findingId: string]: string;
}

type FindingTab = "overview" | "evidence" | "remediation" | "similar";

// ── Helpers ──
const severityConfig = {
  CRITICAL: { color: "#FF4444", bg: "rgba(255,68,68,0.08)", border: "rgba(255,68,68,0.2)" },
  HIGH: { color: "#FF8800", bg: "rgba(255,136,0,0.08)", border: "rgba(255,136,0,0.2)" },
  MEDIUM: { color: "#F59E0B", bg: "rgba(245,158,11,0.08)", border: "rgba(245,158,11,0.2)" },
  LOW: { color: "#10B981", bg: "rgba(16,185,129,0.08)", border: "rgba(16,185,129,0.2)" },
  INFO: { color: "#6720FF", bg: "rgba(103,32,255,0.08)", border: "rgba(103,32,255,0.2)" },
};

function EvidenceBlock({ data }: { data: any }) {
  const [copied, setCopied] = useState(false);
  const code = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="relative bg-surface-container-low dark:bg-surface-container-high rounded-lg overflow-hidden mt-3 border border-outline-variant dark:border-outline/30">
      <div className="flex items-center justify-between px-3 py-2 border-b border-outline-variant dark:border-outline/30 bg-surface-container dark:bg-surface-container-high">
        <span className="text-[10px] font-mono text-on-surface-variant uppercase tracking-wider flex items-center gap-1.5">
          <Code2 size={10} />
          Evidence / POC
        </span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 text-[10px] text-on-surface-variant hover:text-primary transition-all duration-300"
        >
          {copied ? <Check size={10} /> : <Copy size={10} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <div className="overflow-x-auto p-3 max-h-[300px]">
        <pre className="text-[12px] font-mono leading-relaxed text-on-surface-variant">
          <code>{code}</code>
        </pre>
      </div>
    </div>
  );
}

// ── AI Analysis Banner ──
function AIAnalysisBanner({
  aiConfigured,
  isExplaining,
  isChaining,
  onExplainAll,
  onChainAnalysis,
  hasExplanations,
  onDismiss,
}: {
  aiConfigured: boolean | null;
  isExplaining: boolean;
  isChaining: boolean;
  onExplainAll: () => void;
  onChainAnalysis: () => void;
  hasExplanations: boolean;
  onDismiss: () => void;
}) {
  if (hasExplanations) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-6 border border-primary/20 bg-surface dark:bg-surface-container-low rounded-xl p-6 relative shadow-sm"
    >
      <button
        onClick={onDismiss}
        className="absolute top-3 right-3 text-on-surface-variant hover:text-on-surface transition-all duration-300"
      >
        <X size={14} />
      </button>

      <div className="flex items-start gap-4">
        <div className="w-12 h-12 flex items-center justify-center border border-primary/20 bg-primary/10 rounded-xl shrink-0">
          <Brain size={24} className="text-primary" />
        </div>
        <div className="flex-1">
          <h3 className="text-lg font-semibold text-on-surface tracking-tight font-headline mb-1">
            AI Vulnerability Analysis Available
          </h3>
          <p className="text-sm text-on-surface-variant mb-4 max-w-2xl font-body">
            Get instant, developer-friendly explanations for every vulnerability. Plus, discover how these weaknesses
            can be <span className="text-primary font-medium">chained together</span> for a serious system takeover.
          </p>

          {aiConfigured === false ? (
            <div className="flex items-center gap-3">
              <button
                onClick={() => (window.location.href = "/settings")}
                className="flex items-center gap-2 px-5 py-2.5 bg-error/10 text-error border border-error/20 font-bold text-xs tracking-widest uppercase hover:bg-error/20 transition-all duration-300 rounded-lg"
              >
                <Zap size={14} />
                CONFIGURE AI KEY IN SETTINGS
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-3 flex-wrap">
              <button
                onClick={onExplainAll}
                disabled={isExplaining || isChaining}
                className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white font-bold text-xs tracking-widest uppercase hover:bg-primary/90 transition-all duration-300 rounded-lg shadow-glow disabled:opacity-50"
              >
                {isExplaining ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                {isExplaining ? "ANALYZING..." : "EXPLAIN ALL VULNERABILITIES"}
              </button>
              <button
                onClick={onChainAnalysis}
                disabled={isExplaining || isChaining}
                className="flex items-center gap-2 px-5 py-2.5 border border-primary/30 text-primary font-bold text-xs tracking-widest uppercase hover:bg-primary/10 transition-all duration-300 rounded-lg disabled:opacity-50"
              >
                {isChaining ? <Loader2 size={14} className="animate-spin" /> : <Link2 size={14} />}
                {isChaining ? "ANALYZING CHAINS..." : "ATTACK CHAIN ANALYSIS"}
              </button>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}

// ── Attack Chain Panel ──
function AttackChainPanel({
  analysis,
  onClose,
}: {
  analysis: string | null;
  onClose: () => void;
}) {
  if (!analysis) return null;

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      className="mb-6 border border-error/20 bg-error/5 rounded-xl p-6 relative overflow-hidden"
    >
      <button
        onClick={onClose}
        className="absolute top-3 right-3 text-on-surface-variant hover:text-on-surface transition-all duration-300"
      >
        <X size={14} />
      </button>

      <div className="flex items-center gap-3 mb-4">
        <div className="w-8 h-8 flex items-center justify-center border border-error/20 bg-error/10 rounded-lg">
          <Sword size={18} className="text-error" />
        </div>
        <div>
          <h3 className="text-lg font-semibold text-on-surface tracking-tight font-headline">Attack Chain Analysis</h3>
          <p className="text-xs text-on-surface-variant font-body">How vulnerabilities can be chained for system takeover</p>
        </div>
      </div>

      <MarkdownRenderer content={analysis} variant="chain" />
    </motion.div>
  );
}

// ── Main Page ──
export default function FindingsPage() {
  useEffect(() => {
    log.pageMount("Findings");
    return () => log.pageUnmount("Findings");
  }, []);

  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();
  const isMobile = useMobileDetect();

  const [findings, setFindings] = useState<Finding[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [severityFilter, setSeverityFilter] = useState<string>("All");
  const [explanations, setExplanations] = useState<Explanations>({});
  const [isExplaining, setIsExplaining] = useState(false);
  const [aiConfigured, setAiConfigured] = useState<boolean | null>(null);
  const [selectedModel, setSelectedModel] = useState<string>("opencode");
  const [bannerDismissed, setBannerDismissed] = useState(false);
  const [chainAnalysis, setChainAnalysis] = useState<string | null>(null);
  const [isChaining, setIsChaining] = useState(false);
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [selectedEngagement, setSelectedEngagement] = useState<string>("all");
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("All");
  const [selectedFindings, setSelectedFindings] = useState<Set<string>>(new Set());
  const [isBulkVerifying, setIsBulkVerifying] = useState(false);
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);
  const [isBulkExporting, setIsBulkExporting] = useState(false);
  const [activeTab, setActiveTab] = useState<FindingTab>("overview");
  const [remediationContent, setRemediationContent] = useState<Record<string, string>>({});
  const [similarFindings, setSimilarFindings] = useState<Finding[]>([]);

  // Fetch remediation content when the remediation tab is activated
  useEffect(() => {
    if (activeTab !== "remediation" || !selectedFindingId) return;
    const finding = findings.find((f) => f.id === selectedFindingId);
    if (!finding) return;
    const fetchRemediation = async () => {
      try {
        const response = await fetch("/api/ai/explain", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ findings: [finding], model: selectedModel }),
        });
        const data = await response.json();
        if (response.ok) {
          const content = data.explanations?.[finding.id] || data.explanations?.[0] || "";
          setRemediationContent((prev) => ({ ...prev, [selectedFindingId]: content }));
        } else {
          setRemediationContent((prev) => ({ ...prev, [selectedFindingId]: "Failed to generate remediation steps." }));
        }
      } catch (err) {
        setRemediationContent((prev) => ({ ...prev, [selectedFindingId]: "Failed to generate remediation steps." }));
      }
    };
    fetchRemediation();
  }, [activeTab, selectedFindingId, findings, selectedModel]);

  useEffect(() => {
    if (status === "unauthenticated") signIn();
  }, [status, router]);

  // Fetch AI status and preferred model
  useEffect(() => {
    if (status !== "authenticated") return;
    const fetchAIStatus = async () => {
      try {
        const aiResponse = await fetch("/api/ai/explain");
        if (aiResponse.ok) {
          const aiData = await aiResponse.json();
          setAiConfigured(aiData.configured);
        }
        const settingsResponse = await fetch("/api/settings");
        if (settingsResponse.ok) {
          const settingsData = await settingsResponse.json();
          if (settingsData.settings?.preferred_ai_model) {
            setSelectedModel(settingsData.settings.preferred_ai_model);
          }
        }
      } catch (err) {
        console.error("Failed to fetch AI status:", err);
      }
    };
    fetchAIStatus();
  }, [status]);

  // Fetch engagements list
  useEffect(() => {
    if (status !== "authenticated") return;
    const fetchEngagements = async () => {
      try {
        const response = await fetch("/api/engagements?limit=50");
        if (response.ok) {
          const data = await response.json();
          const nextEngagements: Engagement[] = data.engagements || [];
          setEngagements(nextEngagements);
          // Default to the most recent engagement to avoid cross-target blending.
          if (selectedEngagement === "all" && nextEngagements.length > 0) {
            setSelectedEngagement(nextEngagements[0].id);
          }
        }
      } catch (err) {
        console.error("Failed to fetch engagements:", err);
      }
    };
    fetchEngagements();
  }, [status, selectedEngagement]);

  // Fetch findings
  useEffect(() => {
    if (status !== "authenticated") return;
    const fetchFindings = async () => {
      setIsLoading(true);
      try {
        let url = "/api/findings?limit=100";
        if (selectedEngagement && selectedEngagement !== "all") {
          url += `&engagement_id=${selectedEngagement}`;
        }
        const response = await fetch(url);
        if (response.ok) {
          const data = await response.json();
          setFindings(data.findings || []);
        }
      } catch (err) {
        showToast("error", "Failed to load findings");
      } finally {
        setIsLoading(false);
      }
    };
    fetchFindings();
  }, [status, showToast, selectedEngagement]);

  const handleExplainAll = async () => {
    if (filtered.length === 0) {
      showToast("error", "No findings to explain");
      return;
    }
    setIsExplaining(true);
    try {
      const response = await fetch("/api/ai/explain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ findings: filtered, model: selectedModel }),
      });
      const data = await response.json();
      if (!response.ok) {
        showToast("error", data.error || "Failed to generate explanations");
        return;
      }
      setExplanations(data.explanations);
      showToast("success", `Generated ${data.count} explanations using ${data.model}`);
    } catch (err) {
      showToast("error", "Failed to generate explanations");
    } finally {
      setIsExplaining(false);
    }
  };

  const handleChainAnalysis = async () => {
    if (filtered.length === 0) {
      showToast("error", "No findings to analyze");
      return;
    }
    setIsChaining(true);
    try {
      const response = await fetch("/api/ai/chain-analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ findings: filtered, model: selectedModel }),
      });
      const data = await response.json();
      if (!response.ok) {
        showToast("error", data.error || "Failed to generate chain analysis");
        return;
      }
      setChainAnalysis(data.analysis);
      showToast("success", "Attack chain analysis generated");
    } catch (err) {
      showToast("error", "Failed to generate chain analysis");
    } finally {
      setIsChaining(false);
    }
  };

  const handleVerify = async (id: string) => {
    try {
      const response = await fetch(`/api/findings/${id}/verify`, { method: "POST" });
      if (response.ok) {
        showToast("success", "Finding verified!");
        setFindings((prev) => prev.map((f) => (f.id === id ? { ...f, verified: true } : f)));
      }
    } catch (err) {
      showToast("error", "Failed to verify finding");
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Are you sure you want to delete this finding?")) return;
    try {
      const response = await fetch(`/api/findings/${id}`, { method: "DELETE" });
      if (response.ok) {
        showToast("success", "Finding deleted");
        setFindings((prev) => prev.filter((f) => f.id !== id));
        if (selectedFindingId === id) setSelectedFindingId(null);
        // Also remove from selection if present
        setSelectedFindings((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      }
    } catch (err) {
      showToast("error", "Failed to delete finding");
    }
  };

  const handleExplainFinding = async (id: string) => {
    const finding = findings.find((f) => f.id === id);
    if (!finding) return;
    if (!aiConfigured) {
      showToast("error", "Configure AI API key in Settings");
      return;
    }
    setIsExplaining(true);
    try {
      const response = await fetch("/api/ai/explain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ findings: [finding], model: selectedModel }),
      });
      const data = await response.json();
      if (response.ok) {
        setExplanations((prev) => ({ ...prev, ...data.explanations }));
        showToast("success", "Explanation generated");
      }
    } catch (err) {
      showToast("error", "Failed to explain");
    } finally {
      setIsExplaining(false);
    }
  };

  const handleExplainFindingRef = useRef(handleExplainFinding);
  handleExplainFindingRef.current = handleExplainFinding;

  const handleVerifyRef = useRef(handleVerify);
  handleVerifyRef.current = handleVerify;

  useEffect(() => {
    const handleExplainEvent = () => {
      if (selectedFindingId) {
        handleExplainFindingRef.current(selectedFindingId);
      }
    };
    const handleVerifyEvent = () => {
      if (selectedFindingId) {
        handleVerifyRef.current(selectedFindingId);
      }
    };
    window.addEventListener("shortcut:explain-finding", handleExplainEvent);
    window.addEventListener("shortcut:verify-finding", handleVerifyEvent);
    return () => {
      window.removeEventListener("shortcut:explain-finding", handleExplainEvent);
      window.removeEventListener("shortcut:verify-finding", handleVerifyEvent);
    };
  }, [selectedFindingId]);

  useEffect(() => {
    setActiveTab("overview");
    setSimilarFindings([]);
  }, [selectedFindingId]);

  const handleSelectFinding = useCallback((id: string) => {
    setSelectedFindings((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const filtered = useMemo(() => {
    return findings.filter((f) => {
      const matchesSearch =
        f.type.toLowerCase().includes(searchQuery.toLowerCase()) ||
        f.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        f.endpoint.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesSeverity = severityFilter === "All" || f.severity === severityFilter;
      const matchesStatus =
        statusFilter === "All"
          ? true
          : statusFilter === "Verified"
          ? f.verified
          : !f.verified;
      return matchesSearch && matchesSeverity && matchesStatus;
    });
  }, [findings, searchQuery, severityFilter, statusFilter]);

  const handleSelectAll = useCallback(() => {
    if (selectedFindings.size === filtered.length) {
      // Deselect all
      setSelectedFindings(new Set());
    } else {
      // Select all filtered findings
      setSelectedFindings(new Set(filtered.map((f) => f.id)));
    }
  }, [selectedFindings.size, filtered]);

  const handleClearSelection = useCallback(() => {
    setSelectedFindings(new Set());
  }, []);

  const handleBulkVerify = useCallback(async () => {
    if (selectedFindings.size === 0) return;
    setIsBulkVerifying(true);
    try {
      const promises = Array.from(selectedFindings).map((id) =>
        fetch(`/api/findings/${id}/verify`, { method: "POST" })
      );
      const results = await Promise.all(promises);
      const successCount = results.filter((r) => r.ok).length;
      showToast("success", `Verified ${successCount} findings`);
      // Update local state
      setFindings((prev) =>
        prev.map((f) => (selectedFindings.has(f.id) ? { ...f, verified: true } : f))
      );
      setSelectedFindings(new Set());
    } catch (err) {
      showToast("error", "Failed to verify findings");
    } finally {
      setIsBulkVerifying(false);
    }
  }, [selectedFindings, showToast]);

  const handleBulkDelete = useCallback(async () => {
    if (selectedFindings.size === 0) return;
    if (!confirm(`Delete ${selectedFindings.size} selected findings?`)) return;
    setIsBulkDeleting(true);
    try {
      const promises = Array.from(selectedFindings).map((id) =>
        fetch(`/api/findings/${id}`, { method: "DELETE" })
      );
      const results = await Promise.all(promises);
      const successCount = results.filter((r) => r.ok).length;
      showToast("success", `Deleted ${successCount} findings`);
      // Update local state
      setFindings((prev) => prev.filter((f) => !selectedFindings.has(f.id)));
      setSelectedFindings(new Set());
      if (selectedFindingId && selectedFindings.has(selectedFindingId)) {
        setSelectedFindingId(null);
      }
    } catch (err) {
      showToast("error", "Failed to delete findings");
    } finally {
      setIsBulkDeleting(false);
    }
  }, [selectedFindings, selectedFindingId, showToast]);

  const handleBulkExport = useCallback(async () => {
    if (selectedFindings.size === 0) return;
    setIsBulkExporting(true);
    try {
      const selectedFindingsData = filtered.filter((f) => selectedFindings.has(f.id));
      const csv = [
        ["ID", "Type", "Severity", "Endpoint", "Verified", "Confidence"].join(","),
        ...selectedFindingsData.map((f) =>
          [f.id, f.type, f.severity, f.endpoint, f.verified, f.confidence || 0].join(",")
        ),
      ].join("\n");

      const blob = new Blob([csv], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `findings-export-${new Date().toISOString().split("T")[0]}.csv`;
      a.click();
      URL.revokeObjectURL(url);
      showToast("success", `Exported ${selectedFindings.size} findings`);
    } catch (err) {
      showToast("error", "Failed to export findings");
    } finally {
      setIsBulkExporting(false);
    }
  }, [selectedFindings, filtered, showToast]);

  const severityCounts = useMemo(() => {
    return findings.reduce((acc, f) => {
      acc[f.severity] = (acc[f.severity] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);
  }, [findings]);

  const findingsListItems = useMemo(() => {
    if (selectedEngagement !== "all") {
      return filtered.map((finding) => ({
        kind: "finding" as const,
        key: `finding-${finding.id}`,
        finding,
      }));
    }

    const grouped = filtered.reduce(
      (acc, finding) => {
        const target = finding.target_url || "Unknown target";
        if (!acc[target]) acc[target] = [];
        acc[target].push(finding);
        return acc;
      },
      {} as Record<string, Finding[]>,
    );

    return Object.entries(grouped).flatMap(([target, targetFindings]) => [
      {
        kind: "header" as const,
        key: `header-${target}`,
        target,
        count: targetFindings.length,
      },
      ...targetFindings.map((finding) => ({
        kind: "finding" as const,
        key: `finding-${finding.id}`,
        finding,
      })),
    ]);
  }, [filtered, selectedEngagement]);

  const hasExplanations = Object.keys(explanations).length > 0;
  const explainedCount = filtered.filter((f) => explanations[f.id]).length;
  const selectedFinding = findings.find((f) => f.id === selectedFindingId) || null;

  if (status === "loading" || isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background dark:bg-[#0A0A0F]">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!session) return null;

  return (
    <div className="min-h-screen px-6 py-6 bg-background dark:bg-[#0A0A0F] font-body">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-6"
      >
        <div className="flex items-center gap-2 mb-2">
          <Bug size={18} className="text-primary" />
          <span className="text-[11px] font-mono text-on-surface-variant tracking-widest uppercase">
            Vulnerability Engine
          </span>
          <AIStatusBadge />
        </div>
        <h1 className="text-3xl font-semibold text-on-surface tracking-tight font-headline">Findings</h1>
        <p className="text-sm text-on-surface-variant mt-1 font-body">
          {findings.length} total vulnerabilities discovered across the target infrastructure
        </p>
      </motion.div>

      {/* AI Analysis Banner */}
      {!bannerDismissed && (
        <AIAnalysisBanner
          aiConfigured={aiConfigured}
          isExplaining={isExplaining}
          isChaining={isChaining}
          onExplainAll={handleExplainAll}
          onChainAnalysis={handleChainAnalysis}
          hasExplanations={hasExplanations}
          onDismiss={() => setBannerDismissed(true)}
        />
      )}

      {/* Attack Chain Analysis Panel */}
      <AttackChainPanel analysis={chainAnalysis} onClose={() => setChainAnalysis(null)} />

      {/* AI Status Bar (when explanations exist) */}
      <AnimatePresence>
        {hasExplanations && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="flex items-center justify-between mb-4 px-4 py-3 border border-primary/10 bg-surface dark:bg-surface-container-low rounded-xl"
          >
            <div className="flex items-center gap-3">
              <Brain size={16} className="text-primary" />
              <span className="text-sm text-on-surface font-body">
                <span className="text-primary font-semibold">{explainedCount}</span> of{" "}
                <span className="font-semibold">{filtered.length}</span> findings analyzed by AI
              </span>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-[11px] font-mono text-on-surface-variant">
                Model: <span className="text-primary">{selectedModel}</span>
              </span>
              <button
                onClick={handleExplainAll}
                disabled={isExplaining}
                className="flex items-center gap-2 px-4 py-1.5 text-xs font-bold text-primary border border-primary/20 hover:bg-primary/10 transition-all duration-300 rounded-lg disabled:opacity-50"
              >
                {isExplaining ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
                RE-ANALYZE
              </button>
              <button
                onClick={handleChainAnalysis}
                disabled={isChaining}
                className="flex items-center gap-2 px-4 py-1.5 text-xs font-bold text-error border border-error/20 hover:bg-error/10 transition-all duration-300 rounded-lg disabled:opacity-50"
              >
                {isChaining ? <Loader2 size={12} className="animate-spin" /> : <Link2 size={12} />}
                CHAIN ANALYSIS
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Three Column Layout */}
        <div className={`grid gap-6 ${isMobile ? "grid-cols-1" : "grid-cols-12"}`}>
          {/* Left Sidebar - Filters */}
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.1 }}
            className={`${isMobile ? "order-2" : "col-span-12 lg:col-span-3 space-y-4"}`}
          >
          {/* Security Rating */}
          <SecurityRating
            engagementId={selectedEngagement !== "all" ? selectedEngagement : undefined}
            showDetails={true}
          />

          {/* Search */}
          <div className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-3">
            <div className="flex items-center gap-2">
              <Search size={14} className="text-on-surface-variant shrink-0" />
              <input
                type="text"
                placeholder="Search findings..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="flex-1 bg-transparent text-sm text-on-surface outline-none placeholder:text-on-surface-variant/60 font-body"
              />
            </div>
          </div>

          {/* Bulk Selection */}
          {filtered.length > 0 && (
            <div className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-3">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="select-all"
                  checked={selectedFindings.size === filtered.length && filtered.length > 0}
                  ref={(el) => {
                    if (el) el.indeterminate = selectedFindings.size > 0 && selectedFindings.size < filtered.length;
                  }}
                  onChange={handleSelectAll}
                  className="rounded border-outline-variant text-primary focus:ring-primary"
                />
                <label htmlFor="select-all" className="text-xs text-on-surface-variant cursor-pointer">
                  Select All ({selectedFindings.size}/{filtered.length})
                </label>
              </div>
            </div>
          )}

          {/* Severity Filters */}
          <div className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-4">
            <h3 className="text-[11px] font-bold text-on-surface uppercase tracking-wider mb-3 font-headline flex items-center gap-2">
              <AlertTriangle size={12} />
              Severity
            </h3>
            <div className="space-y-1.5">
              {(["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"] as const).map((sev) => (
                <button
                  key={sev}
                  onClick={() => setSeverityFilter(severityFilter === sev ? "All" : sev)}
                  className={`w-full flex items-center justify-between px-3 py-2 rounded-lg text-[11px] font-bold uppercase transition-all duration-300 ${
                    severityFilter === sev
                      ? "bg-primary/10 text-primary border border-primary/20"
                      : "text-on-surface-variant hover:bg-surface-container-high dark:hover:bg-surface-container border border-transparent"
                  }`}
                >
                  <span className="flex items-center gap-2">
                    <Shield size={10} style={{ color: severityConfig[sev].color }} />
                    {sev}
                  </span>
                  <span className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-surface-container-high dark:bg-surface-container text-on-surface-variant">
                    {severityCounts[sev] || 0}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Status Filters */}
          <div className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-4">
            <h3 className="text-[11px] font-bold text-on-surface uppercase tracking-wider mb-3 font-headline flex items-center gap-2">
              <UserCheck size={12} />
              Status
            </h3>
            <div className="space-y-1.5">
              {["All", "Verified", "Unverified"].map((s) => (
                <button
                  key={s}
                  onClick={() => setStatusFilter(s)}
                  className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-[11px] font-bold uppercase transition-all duration-300 ${
                    statusFilter === s
                      ? "bg-primary/10 text-primary border border-primary/20"
                      : "text-on-surface-variant hover:bg-surface-container-high dark:hover:bg-surface-container border border-transparent"
                  }`}
                >
                  <div
                    className={`w-1.5 h-1.5 rounded-full ${
                      s === "Verified" ? "bg-green-500" : s === "Unverified" ? "bg-red-500" : "bg-on-surface-variant"
                    }`}
                  />
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* Scan Targets / Engagements */}
          <div className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-4">
            <h3 className="text-[11px] font-bold text-on-surface uppercase tracking-wider mb-3 font-headline flex items-center gap-2">
              <Target size={12} />
              Scan Targets
            </h3>
            <select
              value={selectedEngagement}
              onChange={(e) => setSelectedEngagement(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-surface-container-low dark:bg-surface-container border border-outline-variant dark:border-outline/30 text-xs text-on-surface outline-none focus:border-primary transition-all duration-300 font-mono"
            >
              <option value="all" className="bg-surface dark:bg-surface-container">
                All Engagements
              </option>
              {engagements.map((eng) => (
                <option key={eng.id} value={eng.id} className="bg-surface dark:bg-surface-container">
                  {eng.target_url} ({eng.findings_count})
                </option>
              ))}
            </select>
          </div>
        </motion.div>

        {/* Center - Findings List */}
        <ScrollReveal direction="up" delay={0.15} className={`${isMobile ? "order-1 col-span-1" : "col-span-12 lg:col-span-5"}`}>
          <StaggerContainer className="space-y-3" staggerDelay={0.04}>
            {findingsListItems.map((item) => {
              if (item.kind === "header") {
                return (
                  <StaggerItem key={item.key}>
                    <div className="px-4 py-2 rounded-lg border border-outline-variant dark:border-outline/30 bg-surface-container-low/50 dark:bg-surface-container/40">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-[10px] font-mono uppercase tracking-wider text-on-surface-variant">
                          Target
                        </span>
                        <span className="text-[10px] font-mono text-on-surface-variant">
                          {item.count} finding{item.count === 1 ? "" : "s"}
                        </span>
                      </div>
                      <div className="mt-1 text-xs font-semibold text-on-surface break-all">
                        {item.target}
                      </div>
                    </div>
                  </StaggerItem>
                );
              }

              const finding = item.finding;
              const sev = severityConfig[finding.severity];
              const isExpanded = expandedRow === finding.id;
              const hasExplanation = !!explanations[finding.id];
              const isSelected = selectedFindingId === finding.id;
              const isBulkSelected = selectedFindings.has(finding.id);

              return (
                <StaggerItem key={finding.id}>
                  <motion.div
                    layout
                    className={`bg-surface dark:bg-surface-container-low rounded-xl border transition-all duration-300 overflow-hidden ${
                      isSelected
                        ? "border-primary/40 shadow-glow"
                        : isBulkSelected
                        ? "border-primary/20 bg-primary/[0.02]"
                        : "border-outline-variant dark:border-outline/30 hover:border-primary/20"
                    }`}
                  >
                {/* Main Row */}
                <div className="flex items-center gap-2 px-4 py-3">
                  <input
                    type="checkbox"
                    checked={isBulkSelected}
                    onChange={(e) => {
                      e.stopPropagation();
                      handleSelectFinding(finding.id);
                    }}
                    onClick={(e) => e.stopPropagation()}
                    className="rounded border-outline-variant text-primary focus:ring-primary shrink-0"
                  />
                  <div
                    className="flex-1 cursor-pointer"
                    onClick={() => {
                      setExpandedRow(isExpanded ? null : finding.id);
                      setSelectedFindingId(isSelected ? null : finding.id);
                    }}
                  >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span
                        className="inline-flex items-center gap-1 text-[10px] font-mono font-bold px-2 py-0.5 rounded border"
                        style={{
                          color: sev.color,
                          borderColor: sev.border,
                          backgroundColor: sev.bg,
                        }}
                      >
                        <Shield size={10} />
                        {finding.severity}
                      </span>
                      {hasExplanation && (
                        <span className="flex items-center gap-1 text-[10px] font-mono text-primary bg-primary/10 border border-primary/20 px-1.5 py-0.5 rounded">
                          <Brain size={10} />
                          AI
                        </span>
                      )}
                      {finding.severity === "CRITICAL" && (
                        <ScannerReveal
                          icon="/assets/holographic-lock.png"
                          text="ALERT"
                          scannedText="BREACH"
                          className="w-16 h-6 shrink-0 border-outline-variant dark:border-outline/30"
                          glowColor={sev.color}
                        />
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] font-mono text-on-surface-variant uppercase">
                        {finding.source_tool}
                      </span>
                      <ChevronDown
                        size={14}
                        className={`text-on-surface-variant transition-transform duration-300 ${
                          isExpanded ? "rotate-180" : ""
                        }`}
                      />
                    </div>
                  </div>
                  <div className="text-sm text-on-surface font-body truncate">{finding.type}</div>
                  <div className="flex items-center justify-between mt-2">
                    <span className="text-[11px] font-mono text-on-surface-variant truncate max-w-[55%]">
                      {finding.endpoint}
                    </span>
                    <div className="flex items-center gap-2">
                      <div className="flex items-center gap-1.5">
                        <div className="w-16 h-1 rounded-full bg-surface-container-high dark:bg-surface-container overflow-hidden">
                          <div
                            className="h-full rounded-full bg-primary"
                            style={{ width: `${(finding.confidence || 0) * 100}%` }}
                          />
                        </div>
                        <span className="text-[10px] font-mono text-primary">
                          {((finding.confidence || 0) * 100).toFixed(0)}%
                        </span>
                      </div>
                      <div
                        className={`w-1.5 h-1.5 rounded-full ${
                          finding.verified ? "bg-green-500" : "bg-red-500"
                        }`}
                      />
                    </div>
                  </div>
                  <div className="mt-2 text-[10px] font-mono text-on-surface-variant/80 truncate">
                    Target: {finding.target_url || "Unknown target"}
                  </div>
                  </div>
                </div>

                {/* AI Explanation Panel */}
                <AnimatePresence>
                  {hasExplanation && (
                    <motion.div
                      layout
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.35, ease: "easeOut" }}
                      className="mx-3 mb-3"
                    >
                      <div className="border border-primary/15 bg-surface-container-low/50 dark:bg-surface-container/50 rounded-lg overflow-hidden">
                        <div className="px-4 py-2 border-b border-primary/10 bg-primary/[0.03] flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <Sparkles size={12} className="text-primary" />
                            <span className="text-[10px] font-bold font-mono text-primary uppercase tracking-widest">
                              AI Analysis
                            </span>
                          </div>
                          <span className="text-[9px] font-mono text-on-surface-variant/60 uppercase tracking-wider">
                            OpenRouter
                          </span>
                        </div>
                        <div className="p-4">
                          <MarkdownRenderer content={explanations[finding.id]} />
                        </div>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>

                {/* No Explanation Yet — Inline Prompt */}
                {!hasExplanation && !isExplaining && (
                  <div className="mx-3 mb-3">
                    <div className="border border-dashed border-outline-variant dark:border-outline/30 bg-surface-container-low/30 dark:bg-surface-container/30 px-4 py-3 rounded-lg">
                      <button
                        onClick={async (e) => {
                          e.stopPropagation();
                          await handleExplainFinding(finding.id);
                        }}
                        className="flex items-center gap-2 text-xs font-bold text-primary/60 hover:text-primary transition-all duration-300"
                      >
                        <Brain size={14} />
                        Click to get AI explanation for this vulnerability
                      </button>
                    </div>
                  </div>
                )}

                {/* Expanded Technical Details */}
                <AnimatePresence>
                  {isExpanded && (
                    <motion.div
                      layout
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.35, ease: "easeOut" }}
                      className="px-4 pb-4 pt-2 border-t border-outline-variant dark:border-outline/30 bg-surface-container-low/30 dark:bg-surface-container/30"
                    >
                      <div className="grid grid-cols-2 gap-4 mb-4">
                        <div>
                          <div className="text-[10px] font-mono text-on-surface-variant uppercase tracking-wider mb-1">
                            Target Endpoint
                          </div>
                          <div className="text-sm text-on-surface font-mono bg-surface dark:bg-surface-container p-2 rounded border border-outline-variant dark:border-outline/30">
                            {finding.endpoint}
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] font-mono text-on-surface-variant uppercase tracking-wider mb-1">
                            Confidence Factor
                          </div>
                          <div className="flex items-center gap-2">
                            <div className="w-24 h-1.5 bg-surface-container-high dark:bg-surface-container rounded-full overflow-hidden">
                              <div
                                className="h-full bg-primary rounded-full"
                                style={{ width: `${(finding.confidence || 0) * 100}%` }}
                              />
                            </div>
                            <span className="text-sm font-mono text-primary">
                              {((finding.confidence || 0) * 100).toFixed(0)}%
                            </span>
                          </div>
                        </div>
                      </div>

                      {finding.evidence && <EvidenceBlock data={finding.evidence} />}

                      <div className="flex items-center gap-3 mt-4">
                        {!finding.verified && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleVerify(finding.id);
                            }}
                            className="flex items-center gap-2 px-4 py-2 text-xs font-bold bg-primary text-white rounded-lg hover:bg-primary/90 transition-all duration-300 shadow-glow"
                          >
                            <CheckCircle2 size={14} />
                            VERIFY FINDING
                          </button>
                        )}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDelete(finding.id);
                          }}
                          className="flex items-center gap-2 px-4 py-2 text-xs font-bold text-error border border-error/20 rounded-lg hover:bg-error/10 transition-all duration-300"
                        >
                          <Trash2 size={14} />
                          PURGE DATA
                        </button>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            </StaggerItem>
          );
        })}

            {filtered.length === 0 && (
              <div className="px-5 py-20 text-center text-on-surface-variant/40 italic text-sm tracking-widest uppercase border border-outline-variant dark:border-outline/30 rounded-xl bg-surface dark:bg-surface-container-low">
                NO FINDINGS DETECTED IN SELECTED TELEMETRY
              </div>
            )}
          </StaggerContainer>
        </ScrollReveal>

        {/* Right Panel - Preview */}
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.3 }}
          className={`${isMobile ? "fixed inset-0 z-50 bg-background/95 dark:bg-[#0A0A0F]/95 backdrop-blur-sm p-4 overflow-y-auto" : "col-span-12 lg:col-span-4"}`}
          style={isMobile && !selectedFinding ? { display: "none" } : {}}
        >
          <div className={isMobile ? "pt-12" : "sticky top-6"}>
            {/* Mobile close button */}
            {isMobile && selectedFinding && (
              <button
                onClick={() => setSelectedFindingId(null)}
                className="fixed top-4 right-4 z-50 p-2 bg-surface-container-low dark:bg-surface-container rounded-lg shadow-glow min-h-[44px] min-w-[44px] flex items-center justify-center"
              >
                <X size={20} />
              </button>
            )}
            <AnimatePresence mode="wait">
              {selectedFinding ? (
                <motion.div
                  key={selectedFinding.id}
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 20 }}
                  className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 overflow-hidden"
                >
                  {/* Preview Header */}
                  <div className="p-4 border-b border-outline-variant dark:border-outline/30">
                    <div className="flex items-center justify-between mb-3">
                      <span
                        className="inline-flex items-center gap-1 text-[10px] font-mono font-bold px-2 py-0.5 rounded border"
                        style={{
                          color: severityConfig[selectedFinding.severity].color,
                          borderColor: severityConfig[selectedFinding.severity].border,
                          backgroundColor: severityConfig[selectedFinding.severity].bg,
                        }}
                      >
                        <Shield size={10} />
                        {selectedFinding.severity}
                      </span>
                      <span className="text-[11px] font-mono text-on-surface-variant">
                        {selectedFinding.id.split("-")[0]}
                      </span>
                    </div>
                    <h3 className="text-lg font-semibold text-on-surface font-headline">
                      {selectedFinding.type}
                    </h3>
                    <p className="text-xs text-on-surface-variant mt-1 font-mono break-all">
                      {selectedFinding.endpoint}
                    </p>
                   </div>

                   {/* Tab Buttons */}
                   <div className="flex gap-2 border-b border-outline-variant px-4 py-2">
                     {["overview", "evidence", "remediation", "similar"].map((tab) => (
                       <button
                         key={tab}
                         onClick={() => setActiveTab(tab as FindingTab)}
                         className={`px-3 py-2 text-xs uppercase ${
                           activeTab === tab ? "border-b-2 border-primary text-primary" : "text-on-surface-variant"
                         }`}
                       >
                         {tab}
                       </button>
                     ))}
                   </div>

                   {/* Tab Content */}
                   <div className="p-4">
                     {activeTab === "overview" && (
                       <div>
                         {/* AI Insights */}
                         {explanations[selectedFinding.id] && (
                           <div className="mb-4">
                             <div className="flex items-center gap-2 mb-2">
                               <Brain size={14} className="text-primary" />
                               <span className="text-[10px] font-bold font-mono text-primary uppercase tracking-widest">
                                 AI Insights
                               </span>
                             </div>
                             <div className="text-xs text-on-surface-variant font-body max-h-[200px] overflow-y-auto">
                               <MarkdownRenderer content={explanations[selectedFinding.id]} />
                             </div>
                           </div>
                         )}

                         {/* Overview Details */}
                         <div className="mb-4">
                           <div className="text-[10px] font-mono text-on-surface-variant uppercase tracking-wider mb-1">Endpoint</div>
                           <div className="text-sm text-on-surface font-mono bg-surface dark:bg-surface-container p-2 rounded border border-outline-variant dark:border-outline/30">
                             {selectedFinding.endpoint}
                           </div>
                         </div>

                         <div className="mb-4">
                           <div className="text-[10px] font-mono text-on-surface-variant uppercase tracking-wider mb-1">Confidence</div>
                           <div className="flex items-center gap-2">
                             <div className="w-24 h-1.5 bg-surface-container-high dark:bg-surface-container rounded-full overflow-hidden">
                               <div className="h-full bg-primary rounded-full" style={{ width: `${(selectedFinding.confidence || 0) * 100}%` }} />
                             </div>
                             <span className="text-sm font-mono text-primary">{((selectedFinding.confidence || 0) * 100).toFixed(0)}%</span>
                           </div>
                         </div>

                         {/* Verify Button */}
                         {!selectedFinding.verified && (
                           <button
                             onClick={() => handleVerify(selectedFinding.id)}
                             className="flex items-center gap-2 px-4 py-2 text-xs font-bold bg-primary text-white rounded-lg hover:bg-primary/90 transition-all duration-300 shadow-glow mb-3"
                           >
                             <CheckCircle2 size={14} />
                             VERIFY FINDING
                           </button>
                         )}

                         {/* Copy as Curl Button */}
                         <button
                           onClick={() => {
                             const baseUrl = selectedFinding.target_url || "";
                             const endpoint = selectedFinding.endpoint.startsWith("/") ? selectedFinding.endpoint : `/${selectedFinding.endpoint}`;
                             const url = `${baseUrl}${endpoint}`;
                             const curl = `curl -X GET "${url}" -H "User-Agent: Argus-Scanner" -H "Accept: */*"`;
                             navigator.clipboard.writeText(curl);
                             showToast("success", "Curl command copied to clipboard");
                           }}
                           className="flex items-center gap-2 px-4 py-2 text-xs font-bold text-primary border border-primary/20 rounded-lg hover:bg-primary/10 transition-all duration-300 mb-3"
                         >
                           <Copy size={14} />
                           COPY AS CURL
                         </button>

                         {/* Attack Chain if available */}
                         {chainAnalysis && (
                           <div className="mt-4">
                             <div className="flex items-center gap-2 mb-2">
                               <Sword size={14} className="text-error" />
                               <span className="text-[10px] font-bold font-mono text-error uppercase tracking-widest">
                                 Attack Chain
                               </span>
                             </div>
                             <div className="flex items-center gap-1 text-xs text-on-surface-variant">
                               <span className="px-2 py-1 bg-surface-container-high dark:bg-surface-container rounded text-[10px] font-mono">
                                 {selectedFinding.type}
                               </span>
                               <ChevronRight size={12} />
                               <span className="px-2 py-1 bg-error/10 text-error rounded text-[10px] font-mono">
                                 Exploit
                               </span>
                               <ChevronRight size={12} />
                               <span className="px-2 py-1 bg-surface-container-high dark:bg-surface-container rounded text-[10px] font-mono">
                                 Impact
                               </span>
                             </div>
                           </div>
                         )}
                       </div>
                     )}

                     {activeTab === "evidence" && (
                       <div>
                         {selectedFinding.evidence ? (
                           <EvidenceBlock data={selectedFinding.evidence} />
                         ) : (
                           <div className="text-xs text-on-surface-variant italic">No evidence available</div>
                         )}
                       </div>
                     )}

                     {activeTab === "remediation" && (
                       <div>
                         {remediationContent[selectedFinding.id] ? (
                           <div className="text-xs text-on-surface-variant">
                             <MarkdownRenderer content={remediationContent[selectedFinding.id]} />
                           </div>
                         ) : (
                           <div className="flex items-center gap-2 text-xs text-on-surface-variant">
                             <Loader2 size={14} className="animate-spin" />
                             Generating remediation steps...
                           </div>
                         )}
                       </div>
                     )}

                     {activeTab === "similar" && (
                       <div>
                         {similarFindings.length > 0 ? (
                           <div className="space-y-2">
                             {similarFindings.map(f => (
                               <div key={f.id} className="p-2 border border-outline-variant rounded-lg cursor-pointer hover:border-primary/20" onClick={() => setSelectedFindingId(f.id)}>
                                 <div className="text-xs font-semibold text-on-surface">{f.type}</div>
                                 <div className="text-[10px] font-mono text-on-surface-variant truncate">{f.endpoint}</div>
                               </div>
                             ))}
                           </div>
                         ) : (
                           <div className="text-xs text-on-surface-variant italic">No similar findings found</div>
                         )}
                     </div>
                    )}
                  </div>
         </motion.div>
               ) : (
                <motion.div
                  key="empty"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-8 text-center"
                >
                  <div className="w-16 h-16 mx-auto mb-4 flex items-center justify-center rounded-full bg-surface-container-high dark:bg-surface-container">
                    <Target size={24} className="text-on-surface-variant" />
                  </div>
                  <h3 className="text-sm font-semibold text-on-surface font-headline mb-1">
                    Select a Finding
                  </h3>
                  <p className="text-xs text-on-surface-variant font-body">
                    Click on any finding in the list to view detailed analysis and AI insights.
                  </p>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </motion.div>
      </div>

      {/* Mobile Bottom Action Bar */}
      {isMobile && selectedFinding && (
        <motion.div
          initial={{ y: 100 }}
          animate={{ y: 0 }}
          className="fixed bottom-0 left-0 right-0 z-50 bg-surface dark:bg-surface-container-low border-t border-outline-variant dark:border-outline/30 p-3 flex items-center gap-3 safe-area-inset-bottom"
        >
          <button
            onClick={() => {
              handleVerify(selectedFinding.id);
            }}
            disabled={selectedFinding.verified}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-3 text-xs font-bold bg-primary text-white rounded-lg hover:bg-primary/90 transition-all duration-300 shadow-glow disabled:opacity-50 min-h-[44px]"
          >
            <Wrench size={16} />
            {selectedFinding.verified ? "VERIFIED" : "REMEDIATE"}
          </button>
          <button
            onClick={() => handleDelete(selectedFinding.id)}
            className="px-4 py-3 text-xs font-bold text-error border border-error/20 rounded-lg hover:bg-error/10 transition-all duration-300 min-h-[44px] min-w-[44px] flex items-center justify-center"
          >
            <Trash2 size={16} />
          </button>
          <button
            onClick={() => setSelectedFindingId(null)}
            className="px-4 py-3 text-xs font-bold text-on-surface-variant border border-outline-variant rounded-lg hover:bg-surface-container-high transition-all duration-300 min-h-[44px] min-w-[44px] flex items-center justify-center"
          >
            <X size={16} />
          </button>
        </motion.div>
      )}
    </div>
  );
}
