"use client";

import { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
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
} from "lucide-react";
import ScannerReveal from "@/components/effects/ScannerReveal";
import { AIStatusBadge } from "@/components/ui-custom/AIStatus";
import { MarkdownRenderer } from "@/components/ui-custom/MarkdownRenderer";

// ── Types ──
interface Finding {
  id: string;
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

// ── Helpers ──
const severityConfig = {
  CRITICAL: { color: "#FF4444", bg: "rgba(255,68,68,0.08)", border: "rgba(255,68,68,0.2)" },
  HIGH: { color: "#FF8800", bg: "rgba(255,136,0,0.08)", border: "rgba(255,136,0,0.2)" },
  MEDIUM: { color: "var(--prism-cream)", bg: "var(--bg-surface)", border: "var(--border-structural)" },
  LOW: { color: "var(--text-secondary)", bg: "var(--bg-surface)", border: "var(--border-structural)" },
  INFO: { color: "var(--prism-cyan)", bg: "var(--bg-surface)", border: "var(--border-structural)" },
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
    <div className="relative bg-void border border-structural rounded overflow-hidden mt-3">
      <div className="flex items-center justify-between px-3 py-2 border-b border-structural">
        <span className="text-[10px] font-mono text-text-secondary uppercase tracking-wider">Evidence / POC</span>
        <button onClick={handleCopy} className="flex items-center gap-1 text-[10px] text-text-secondary hover:text-prism-cyan transition-colors">
          {copied ? <Check size={10} /> : <Copy size={10} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <div className="overflow-x-auto p-3 max-h-[300px]">
        <pre className="text-[12px] font-mono leading-relaxed text-text-secondary"><code>{code}</code></pre>
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
    <div className="mb-6 border border-prism-cyan/30 bg-surface/40 p-6 relative">
      <button onClick={onDismiss} className="absolute top-3 right-3 text-text-secondary hover:text-text-primary transition-colors">
        <X size={14} />
      </button>
      
      <div className="flex items-start gap-4">
        <div className="w-12 h-12 flex items-center justify-center border border-prism-cyan/30 bg-prism-cyan/10 shrink-0">
          <Brain size={24} className="text-prism-cyan" />
        </div>
        <div className="flex-1">
          <h3 className="text-lg font-semibold text-text-primary tracking-tight mb-1">
            AI Vulnerability Analysis Available
          </h3>
          <p className="text-sm text-text-secondary mb-4 max-w-2xl">
            Get instant, developer-friendly explanations for every vulnerability. Plus, discover how these weaknesses 
            can be <span className="text-prism-cream font-medium">chained together</span> for a serious system takeover.
          </p>
          
          {aiConfigured === false ? (
            <div className="flex items-center gap-3">
              <button
                onClick={() => window.location.href = "/settings"}
                className="flex items-center gap-2 px-5 py-2.5 bg-red-500/20 text-red-400 border border-red-500/30 font-bold text-xs tracking-widest uppercase hover:bg-red-500/30 transition-all"
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
                className="flex items-center gap-2 px-5 py-2.5 bg-prism-cream text-void font-bold text-xs tracking-widest uppercase hover:opacity-90 transition-all shadow-glow-cream disabled:opacity-50"
              >
                {isExplaining ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                {isExplaining ? "ANALYZING..." : "EXPLAIN ALL VULNERABILITIES"}
              </button>
              <button
                onClick={onChainAnalysis}
                disabled={isExplaining || isChaining}
                className="flex items-center gap-2 px-5 py-2.5 border border-prism-cyan/40 text-prism-cyan font-bold text-xs tracking-widest uppercase hover:bg-prism-cyan/10 transition-all disabled:opacity-50"
              >
                {isChaining ? <Loader2 size={14} className="animate-spin" /> : <Link2 size={14} />}
                {isChaining ? "ANALYZING CHAINS..." : "ATTACK CHAIN ANALYSIS"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
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
    <div className="mb-6 border border-red-500/30 bg-red-500/5 p-6 relative">
      <button onClick={onClose} className="absolute top-3 right-3 text-text-secondary hover:text-text-primary transition-colors">
        <X size={14} />
      </button>
      
      <div className="flex items-center gap-3 mb-4">
        <div className="w-8 h-8 flex items-center justify-center border border-red-500/30 bg-red-500/10">
          <Sword size={18} className="text-red-400" />
        </div>
        <div>
          <h3 className="text-lg font-semibold text-text-primary tracking-tight">Attack Chain Analysis</h3>
          <p className="text-xs text-text-secondary">How vulnerabilities can be chained for system takeover</p>
        </div>
      </div>
      
      <MarkdownRenderer content={analysis} variant="chain" />
    </div>
  );
}

// ── Main Page ──
export default function FindingsPage() {
  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();

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

  useEffect(() => {
    if (status === "unauthenticated") signIn();
  }, [status, router]);

  // Fetch AI status and preferred model
  useEffect(() => {
    if (status !== "authenticated") return;
    const fetchAIStatus = async () => {
      try {
        // Check if AI is configured
        const aiResponse = await fetch("/api/ai/explain");
        if (aiResponse.ok) {
          const aiData = await aiResponse.json();
          setAiConfigured(aiData.configured);
        }
        // Get preferred model from settings
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
          setEngagements(data.engagements || []);
        }
      } catch (err) {
        console.error("Failed to fetch engagements:", err);
      }
    };
    fetchEngagements();
  }, [status]);

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
      }
    } catch (err) {
      showToast("error", "Failed to delete finding");
    }
  };

  const filtered = useMemo(() => {
    return findings.filter((f) => {
      const matchesSearch =
        f.type.toLowerCase().includes(searchQuery.toLowerCase()) ||
        f.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        f.endpoint.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesSeverity = severityFilter === "All" || f.severity === severityFilter;
      return matchesSearch && matchesSeverity;
    });
  }, [findings, searchQuery, severityFilter]);

  const severityCounts = useMemo(() => {
    return findings.reduce((acc, f) => {
      acc[f.severity] = (acc[f.severity] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);
  }, [findings]);

  const hasExplanations = Object.keys(explanations).length > 0;
  const explainedCount = filtered.filter((f) => explanations[f.id]).length;

  if (status === "loading" || isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-void">
        <Loader2 className="h-8 w-8 animate-spin text-prism-cream" />
      </div>
    );
  }

  if (!session) return null;

  return (
    <div className="min-h-screen px-8 py-8 bg-void">
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-2">
          <Bug size={18} className="text-prism-cream" />
          <span className="text-[11px] font-mono text-text-secondary tracking-widest uppercase">Vulnerability Engine</span>
          <AIStatusBadge />
        </div>
        <h1 className="text-4xl font-semibold text-text-primary tracking-tight">FINDINGS</h1>
        <p className="text-sm text-text-secondary mt-2">
          {findings.length} total vulnerabilities discovered across the target infrastructure
        </p>
      </div>

      {/* Severity Summary Bar */}
      <div className="flex gap-3 mb-6">
        {(["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"] as const).map((sev) => (
          <button
            key={sev}
            onClick={() => setSeverityFilter(severityFilter === sev ? "All" : sev)}
            className={`flex items-center gap-2 px-4 py-2 border transition-all duration-200 ${
              severityFilter === sev
                ? "border-prism-cream/40 bg-surface/50"
                : "border-structural bg-surface/30 hover:border-text-secondary/20"
            }`}
          >
            <AlertTriangle size={14} style={{ color: severityConfig[sev].color }} />
            <span className="text-[10px] text-text-primary font-bold uppercase">{sev}</span>
            <span className="text-[11px] font-mono px-1.5 py-0.5 ml-1" style={{ color: severityConfig[sev].color, backgroundColor: "var(--structural)" }}>
              {severityCounts[sev] || 0}
            </span>
          </button>
        ))}
      </div>

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
      {hasExplanations && (
        <div className="flex items-center justify-between mb-4 px-4 py-3 border border-prism-cyan/20 bg-surface/20">
          <div className="flex items-center gap-3">
            <Brain size={16} className="text-prism-cyan" />
            <span className="text-sm text-text-primary">
              <span className="text-prism-cyan font-semibold">{explainedCount}</span> of <span className="font-semibold">{filtered.length}</span> findings analyzed by AI
            </span>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-[11px] font-mono text-text-secondary">
              Model: <span className="text-prism-cyan">{selectedModel}</span>
            </span>
            <button
              onClick={handleExplainAll}
              disabled={isExplaining}
              className="flex items-center gap-2 px-4 py-1.5 text-xs font-bold text-prism-cyan border border-prism-cyan/30 hover:bg-prism-cyan/10 transition-all disabled:opacity-50"
            >
              {isExplaining ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
              RE-ANALYZE
            </button>
            <button
              onClick={handleChainAnalysis}
              disabled={isChaining}
              className="flex items-center gap-2 px-4 py-1.5 text-xs font-bold text-red-400 border border-red-400/30 hover:bg-red-400/10 transition-all disabled:opacity-50"
            >
              {isChaining ? <Loader2 size={12} className="animate-spin" /> : <Link2 size={12} />}
              CHAIN ANALYSIS
            </button>
          </div>
        </div>
      )}

      {/* Toolbar */}
      <div className="flex items-center gap-3 mb-4">
        <div className="flex-1 flex items-center gap-2 px-3 py-2 border border-structural bg-surface/30 transition-all">
          <Search size={14} className="text-text-secondary shrink-0" />
          <input
            type="text"
            placeholder="Search patterns, endpoints, or identifiers..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="flex-1 bg-transparent text-sm text-text-primary outline-none placeholder:text-text-secondary/60"
          />
        </div>

        {/* Engagement Filter */}
        <select
          value={selectedEngagement}
          onChange={(e) => setSelectedEngagement(e.target.value)}
          className="px-3 py-2 border border-structural bg-surface/30 text-sm text-text-primary outline-none focus:border-prism-cream transition-colors font-mono text-xs"
        >
          <option value="all" className="bg-surface">All Engagements</option>
          {engagements.map((eng) => (
            <option key={eng.id} value={eng.id} className="bg-surface">
              {eng.target_url} ({eng.findings_count} findings)
            </option>
          ))}
        </select>

        <button className="flex items-center gap-2 px-4 py-2 border border-structural text-text-secondary hover:text-text-primary hover:border-text-secondary/40 transition-all text-sm uppercase font-bold tracking-widest text-[10px]">
          <Filter size={14} />
          Filter
        </button>
      </div>

      {/* Findings List */}
      <div className="space-y-4">
        {filtered.map((finding) => {
          const sev = severityConfig[finding.severity];
          const isExpanded = expandedRow === finding.id;
          const hasExplanation = !!explanations[finding.id];

          return (
            <div key={finding.id} className="border border-structural bg-surface/10 hover:border-text-secondary/20 transition-colors">
              {/* Main Row */}
              <div
                className="grid grid-cols-[100px_120px_1fr_120px_100px_40px] gap-4 px-5 py-4 items-center cursor-pointer"
                onClick={() => setExpandedRow(isExpanded ? null : finding.id)}
              >
                <span className="text-[11px] font-mono text-text-secondary uppercase">{finding.id.split("-")[0]}</span>
                <div>
                  <span
                    className="inline-flex items-center gap-1 text-[10px] font-mono font-bold px-2 py-0.5 border"
                    style={{ color: sev.color, borderColor: "var(--border-structural)", backgroundColor: "transparent" }}
                  >
                    <Shield size={10} />
                    {finding.severity}
                  </span>
                </div>
                <div className="text-sm text-text-primary truncate flex items-center gap-3">
                  {finding.type}
                  {finding.severity === "CRITICAL" && (
                    <ScannerReveal
                      icon="/assets/holographic-lock.png"
                      text="ALERT"
                      scannedText="BREACH"
                      className="w-16 h-7 shrink-0 border-structural"
                      glowColor={sev.color}
                    />
                  )}
                  {/* AI Badge */}
                  {hasExplanation && (
                    <span className="flex items-center gap-1 text-[10px] font-mono text-prism-cyan bg-prism-cyan/10 border border-prism-cyan/20 px-1.5 py-0.5">
                      <Brain size={10} />
                      AI
                    </span>
                  )}
                </div>
                <span className="text-[11px] font-mono text-text-secondary uppercase">{finding.source_tool}</span>
                <div className="flex items-center gap-2">
                  <div className={`w-1.5 h-1.5 rounded-full ${finding.verified ? "bg-green-500" : "bg-red-500"}`} />
                  <span className="text-[11px] text-text-secondary uppercase">{finding.verified ? "Verified" : "Unverified"}</span>
                </div>
                <ChevronDown size={14} className={`text-text-secondary transition-transform ${isExpanded ? "rotate-180" : ""}`} />
              </div>

              {/* AI Explanation Panel — visually separated from the finding card */}
              {hasExplanation && (
                <div className="mt-3 mb-1 mx-2">
                  {/* Connector line */}
                  <div className="flex justify-center mb-1">
                    <div className="w-px h-3 bg-gradient-to-b from-transparent to-prism-cyan/30" />
                  </div>
                  <div className="border border-prism-cyan/15 bg-surface/[0.03] shadow-[0_0_20px_rgba(0,0,0,0.15)]">
                    {/* Header bar */}
                    <div className="px-4 py-2.5 border-b border-prism-cyan/10 bg-prism-cyan/[0.03] flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Sparkles size={12} className="text-prism-cyan" />
                        <span className="text-[10px] font-bold font-mono text-prism-cyan uppercase tracking-widest">AI Analysis</span>
                      </div>
                      <span className="text-[9px] font-mono text-text-secondary/40 uppercase tracking-wider">OpenRouter</span>
                    </div>
                    {/* Content */}
                    <div className="p-5">
                      <MarkdownRenderer content={explanations[finding.id]} />
                    </div>
                  </div>
                </div>
              )}

              {/* No Explanation Yet — Inline Prompt */}
              {!hasExplanation && !isExplaining && (
                <div className="mt-2 mx-2 mb-1">
                  <div className="flex justify-center mb-1">
                    <div className="w-px h-3 bg-gradient-to-b from-transparent to-text-secondary/10" />
                  </div>
                  <div className="border border-dashed border-structural/40 bg-surface/[0.02] px-5 py-3">
                    <button
                      onClick={async (e) => {
                        e.stopPropagation();
                        if (!aiConfigured) { showToast("error", "Configure AI API key in Settings"); return; }
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
                      }}
                      className="flex items-center gap-2 text-xs font-bold text-prism-cyan/50 hover:text-prism-cyan transition-colors"
                    >
                      <Brain size={14} />
                      Click to get AI explanation for this vulnerability
                    </button>
                  </div>
                </div>
              )}

              {/* Expanded Technical Details */}
              {isExpanded && (
                <div className="px-5 pb-5 pt-2 border-t border-structural bg-surface/10">
                  <div className="grid grid-cols-2 gap-6 mb-4">
                    <div>
                      <div className="text-[10px] font-mono text-text-secondary uppercase tracking-wider mb-1">Target Endpoint</div>
                      <div className="text-sm text-text-primary font-mono bg-surface/30 p-2 border border-structural">{finding.endpoint}</div>
                    </div>
                    <div>
                      <div className="text-[10px] font-mono text-text-secondary uppercase tracking-wider mb-1">Confidence Factor</div>
                      <div className="flex items-center gap-2">
                        <div className="w-24 h-1.5 bg-surface/20">
                          <div className="h-full bg-prism-cyan" style={{ width: `${(finding.confidence || 0) * 100}%` }} />
                        </div>
                        <span className="text-sm font-mono text-prism-cyan">{((finding.confidence || 0) * 100).toFixed(0)}%</span>
                      </div>
                    </div>
                  </div>

                  {finding.evidence && <EvidenceBlock data={finding.evidence} />}

                  <div className="flex items-center gap-3 mt-4">
                    {!finding.verified && (
                      <button
                        onClick={(e) => { e.stopPropagation(); handleVerify(finding.id); }}
                        className="flex items-center gap-2 px-4 py-2 text-xs font-bold bg-prism-cream text-void border border-transparent hover:opacity-90 transition-all shadow-glow-cream"
                      >
                        <CheckCircle2 size={14} />
                        VERIFY FINDING
                      </button>
                    )}
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDelete(finding.id); }}
                      className="flex items-center gap-2 px-4 py-2 text-xs font-bold text-red-500 border border-red-500/20 hover:bg-red-500/10 transition-all"
                    >
                      <Trash2 size={14} />
                      PURGE DATA
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {filtered.length === 0 && (
          <div className="px-5 py-20 text-center text-text-secondary/40 italic text-sm tracking-widest uppercase border border-structural">
            NO FINDINGS DETECTED IN SELECTED TELEMETRY
          </div>
        )}
      </div>
    </div>
  );
}
