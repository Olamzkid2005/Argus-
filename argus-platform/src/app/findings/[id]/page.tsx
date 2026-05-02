"use client";

/**
 * Finding Detail Page — /findings/[id]
 *
 * Five sections:
 * 1. Header Bar (severity badge, type, endpoint, verify action)
 * 2. Evidence Panel (tabbed: Request | Response | Payload)
 * 3. Classification & Scoring (OWASP, CWE, CVSS, Confidence, FP)
 * 4. Reproduction Steps (numbered list)
 * 5. AI Explanation (lazy-loaded via POST /api/ai/explain)
 */

import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { log } from "@/lib/logger";
import {
  ArrowLeft,
  ShieldAlert,
  CheckCircle2,
  Loader2,
  Sparkles,
  AlertTriangle,
  Bug,
  FileCode,
  Radio,
  ExternalLink,
  ChevronRight,
  Package,
  GitBranch,
  Hash,
} from "lucide-react";

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
  confidence: number;
  cvss_score?: number | null;
  owasp_category?: string | null;
  cwe_id?: string | null;
  fp_likelihood?: number | null;
  evidence: Record<string, unknown>;
  repro_steps?: string[] | null;
  created_at: string;
}

interface AIExplanation {
  summary: string;
  impact: string;
  fix: string;
  developer_story: string;
}

// ── Helpers ──

const SEVERITY_CONFIG: Record<string, { color: string; bg: string; border: string; label: string }> = {
  CRITICAL: { color: "text-red-500", bg: "bg-red-500/10", border: "border-red-500/30", label: "CRITICAL" },
  HIGH: { color: "text-orange-500", bg: "bg-orange-500/10", border: "border-orange-500/30", label: "HIGH" },
  MEDIUM: { color: "text-yellow-500", bg: "bg-yellow-500/10", border: "border-yellow-500/30", label: "MEDIUM" },
  LOW: { color: "text-blue-400", bg: "bg-blue-400/10", border: "border-blue-400/30", label: "LOW" },
  INFO: { color: "text-gray-400", bg: "bg-gray-400/10", border: "border-gray-400/30", label: "INFO" },
};

function severityConfig(severity: string) {
  return SEVERITY_CONFIG[severity] || SEVERITY_CONFIG.INFO;
}

function cvssColor(score: number): string {
  if (score >= 9.0) return "text-red-500 bg-red-500/10 border-red-500/30";
  if (score >= 7.0) return "text-orange-500 bg-orange-500/10 border-orange-500/30";
  if (score >= 4.0) return "text-yellow-500 bg-yellow-500/10 border-yellow-500/30";
  return "text-blue-400 bg-blue-400/10 border-blue-400/30";
}

// ── Syntax-highlighted code block ──

function CodeBlock({ label, content, tone }: { label: string; content: string; tone?: "red" | "normal" }) {
  const borderColor = tone === "red" ? "border-red-500/20" : "border-outline/20";
  const bgColor = tone === "red" ? "bg-red-950/10" : "bg-surface-container";
  return (
    <div className={`rounded-xl border ${borderColor} overflow-hidden`}>
      <div className={`px-4 py-2 text-[10px] font-bold uppercase tracking-widest ${bgColor} text-on-surface-variant border-b ${borderColor}`}>
        {label}
      </div>
      <pre className="p-4 text-xs font-mono text-on-surface leading-relaxed overflow-x-auto max-h-80 overflow-y-auto bg-black/5 dark:bg-black/20">
        <code>{content}</code>
      </pre>
    </div>
  );
}

// ── Type badge ──

function TypeBadge({ type }: { type: string }) {
  const iconMap: Record<string, React.ReactNode> = {
    SQL_INJECTION: <Bug size={14} />,
    XSS: <AlertTriangle size={14} />,
    COMMAND_INJECTION: <ShieldAlert size={14} />,
  };
  const icon = iconMap[type] || <Bug size={14} />;
  return (
    <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold bg-primary/10 text-primary border border-primary/20">
      {icon}
      {type}
    </span>
  );
}

// ── Progress Bar ──

function ProgressBar({ value, label, color }: { value: number; label: string; color?: string }) {
  const pct = Math.min(Math.max(value * 100, 0), 100);
  const barColor = color || (pct >= 70 ? "bg-red-500" : pct >= 40 ? "bg-yellow-500" : "bg-green-500");
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-[10px] font-mono text-on-surface-variant">
        <span>{label}</span>
        <span>{pct.toFixed(0)}%</span>
      </div>
      <div className="w-full h-2 bg-surface-container-high rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ── Main Page ──

export default function FindingDetailPage() {
  const params = useParams();
  const router = useRouter();
  const findingId = params.id as string;

  const [finding, setFinding] = useState<Finding | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [evidenceTab, setEvidenceTab] = useState<"request" | "response" | "payload">("request");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiExplanation, setAiExplanation] = useState<AIExplanation | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);

  // Fetch finding
  useEffect(() => {
    if (!findingId) return;
    setLoading(true);
    setError(null);

    fetch(`/api/findings/${findingId}`)
      .then((r) => {
        if (!r.ok) throw new Error("Finding not found");
        return r.json();
      })
      .then((data) => {
        if (!data.finding) throw new Error("Finding not found");
        setFinding(data.finding);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [findingId]);

  // Verify finding
  const handleVerify = useCallback(async () => {
    if (!finding || verifying) return;
    setVerifying(true);
    try {
      const res = await fetch("/api/findings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "verify", finding_ids: [finding.id] }),
      });
      if (res.ok) {
        setFinding((prev) => (prev ? { ...prev, verified: true } : prev));
      }
    } finally {
      setVerifying(false);
    }
  }, [finding, verifying]);

  // AI Explanation
  const handleAiExplain = useCallback(async () => {
    if (!finding || aiLoading) return;
    setAiLoading(true);
    setAiError(null);
    try {
      const res = await fetch("/api/ai/explain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ finding_id: finding.id }),
      });
      if (!res.ok) {
        if (res.status === 400) {
          setAiError("Configure your OpenRouter key in Settings to use AI explanations");
        } else {
          throw new Error("AI explanation failed");
        }
        return;
      }
      const data = await res.json();
      setAiExplanation(data.explanation || data);
    } catch (e) {
      setAiError(e instanceof Error ? e.message : "AI explanation failed");
    } finally {
      setAiLoading(false);
    }
  }, [finding, aiLoading]);

  // Loading state
  if (loading) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p className="text-sm font-medium text-on-surface-variant animate-pulse">
            Loading finding...
          </p>
        </div>
      </div>
    );
  }

  // Error state
  if (error || !finding) {
    return (
      <div className="min-h-screen bg-surface flex items-center justify-center">
        <div className="text-center space-y-4">
          <ShieldAlert className="h-12 w-12 text-red-500 mx-auto" />
          <h2 className="text-lg font-bold text-on-surface">Finding Not Found</h2>
          <p className="text-sm text-on-surface-variant">{error || "The requested finding does not exist."}</p>
          <button
            onClick={() => router.push("/findings")}
            className="px-4 py-2 text-sm font-bold bg-primary text-white rounded-lg hover:bg-primary/90"
          >
            Back to Findings
          </button>
        </div>
      </div>
    );
  }

  const sevCfg = severityConfig(finding.severity);
  const evidence = finding.evidence || {};
  const evidenceRequest = typeof evidence.request === "string" ? evidence.request : JSON.stringify(evidence.request, null, 2);
  const evidenceResponse = typeof evidence.response === "string" ? evidence.response : JSON.stringify(evidence.response, null, 2);
  const evidencePayload = typeof evidence.payload === "string" ? evidence.payload : JSON.stringify(evidence.payload, null, 2);
  const hasPayload = !!evidence.payload;
  const hasRequest = !!evidence.request;
  const hasResponse = !!evidence.response;
  const reproSteps = finding.repro_steps || [];
  const isSca = finding.type === "DEPENDENCY_VULNERABILITY" || ["npm-audit", "pip-audit", "govulncheck", "trivy", "snyk"].includes(finding.source_tool);
  const scaPackage = evidence.package as string | undefined;
  const scaVersion = evidence.version as string | undefined;
  const scaVulnVersions = evidence.vulnerable_versions as string | undefined;
  const scaFixVersion = (evidence.fix_version || evidence.fixed_version) as string | undefined;
  const scaFixAvailable = evidence.fix_available as boolean | undefined;
  const scaCves = (evidence.cve || evidence.cves) as string[] | string | undefined;
  const scaCveList: string[] = Array.isArray(scaCves) ? scaCves : scaCves ? [scaCves] : [];

  return (
    <div className="min-h-screen bg-surface">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">

        {/* ── Back Button ── */}
        <button
          onClick={() => router.push("/findings")}
          className="flex items-center gap-2 text-xs font-bold text-on-surface-variant hover:text-on-surface transition-colors"
        >
          <ArrowLeft size={14} />
          Back to Findings
        </button>

        {/* ═══════════════════════════════════════
           SECTION 1: HEADER BAR
           ═══════════════════════════════════════ */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-surface-container rounded-2xl border border-outline/20 p-6 space-y-4"
        >
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <span className={`px-3 py-1 rounded-full text-xs font-bold ${sevCfg.bg} ${sevCfg.color} ${sevCfg.border} border`}>
                  {sevCfg.label}
                </span>
                <TypeBadge type={finding.type} />
                {finding.verified ? (
                  <span className="flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-green-500/10 text-green-500 border border-green-500/20">
                    <CheckCircle2 size={12} />
                    Verified
                  </span>
                ) : (
                  <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-yellow-500/10 text-yellow-500 border border-yellow-500/20">
                    Unverified
                  </span>
                )}
              </div>

              <h1 className="text-2xl font-bold font-headline text-on-surface">
                {finding.type.replace(/_/g, " ")}
              </h1>

              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs font-mono text-on-surface-variant">
                <span className="flex items-center gap-1">
                  <Radio size={12} />
                  {finding.endpoint}
                </span>
                <span className="opacity-30">|</span>
                <span>Tool: {finding.source_tool}</span>
                <span className="opacity-30">|</span>
                <span>Confidence: {((finding.confidence || 0) * 100).toFixed(0)}%</span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {!finding.verified && (
                <button
                  onClick={handleVerify}
                  disabled={verifying}
                  className="flex items-center gap-2 px-4 py-2 text-xs font-bold bg-primary text-white rounded-xl hover:bg-primary/90 transition-all disabled:opacity-50"
                >
                  {verifying ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                  {verifying ? "Verifying..." : "Verify"}
                </button>
              )}
              <button
                onClick={() => router.push(`/findings`)}
                className="px-4 py-2 text-xs font-bold border border-outline/30 text-on-surface-variant rounded-xl hover:bg-surface-container-high transition-all"
              >
                Back to List
              </button>
            </div>
          </div>
        </motion.div>

        {/* ═══════════════════════════════════════
           SCA DETAILS (dependency vulnerability)
           ═══════════════════════════════════════ */}
        {isSca && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.03 }}
            className="bg-surface-container rounded-2xl border border-outline/20 p-6 space-y-4"
          >
            <h2 className="text-sm font-bold font-headline text-on-surface flex items-center gap-2">
              <Package size={16} className="text-primary" />
              Dependency Vulnerability Details
            </h2>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {/* Package Name */}
              {scaPackage && (
                <div className="space-y-1.5">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Package</div>
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono bg-surface-container-high text-on-surface border border-outline/20">
                    <Package size={12} />
                    {scaPackage}
                  </span>
                </div>
              )}

              {/* Current Version */}
              {scaVersion && (
                <div className="space-y-1.5">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Current Version</div>
                  <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono bg-surface-container-high text-on-surface border border-outline/20">
                    <GitBranch size={12} />
                    {scaVersion}
                  </span>
                </div>
              )}

              {/* Vulnerable Range */}
              {scaVulnVersions && (
                <div className="space-y-1.5">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Vulnerable Range</div>
                  <span className="inline-flex items-center px-3 py-1.5 rounded-lg text-xs font-mono bg-red-500/10 text-red-400 border border-red-500/20">
                    {scaVulnVersions}
                  </span>
                </div>
              )}

              {/* Fix Version */}
              <div className="space-y-1.5">
                <div className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Fix</div>
                {scaFixVersion ? (
                  <span className="inline-flex items-center px-3 py-1.5 rounded-lg text-xs font-mono bg-green-500/10 text-green-400 border border-green-500/20">
                    {scaFixVersion}
                  </span>
                ) : scaFixAvailable === false ? (
                  <span className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-mono bg-amber-500/10 text-amber-400 border border-amber-500/20">
                    <AlertTriangle size={12} />
                    No fix available
                  </span>
                ) : (
                  <span className="text-xs text-on-surface-variant italic">N/A</span>
                )}
              </div>
            </div>

            {/* CVE List */}
            {scaCveList.length > 0 && (
              <div className="space-y-2">
                <div className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">
                  Related CVEs ({scaCveList.length})
                </div>
                <div className="flex flex-wrap gap-2">
                  {scaCveList.map((cve) => {
                    const cveId = typeof cve === "string" ? cve.trim() : "";
                    if (!cveId || !cveId.startsWith("CVE-")) return null;
                    return (
                      <a
                        key={cveId}
                        href={`https://nvd.nist.gov/vuln/detail/${cveId}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 hover:bg-cyan-500/20 transition-colors"
                      >
                        <Hash size={10} />
                        {cveId}
                        <ExternalLink size={10} />
                      </a>
                    );
                  })}
                </div>
              </div>
            )}
          </motion.div>
        )}

        {/* ═══════════════════════════════════════
           SECTION 2: EVIDENCE PANEL
           ═══════════════════════════════════════ */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="bg-surface-container rounded-2xl border border-outline/20 p-6 space-y-4"
        >
          <h2 className="text-sm font-bold font-headline text-on-surface flex items-center gap-2">
            <FileCode size={16} className="text-primary" />
            Evidence
          </h2>

          {!hasRequest && !hasResponse && !hasPayload ? (
            <p className="text-xs text-on-surface-variant italic">No evidence recorded for this finding.</p>
          ) : (
            <>
              {/* Tabs */}
              <div className="flex gap-1 border-b border-outline/20 pb-1">
                {hasRequest && (
                  <button
                    onClick={() => setEvidenceTab("request")}
                    className={`px-4 py-2 text-xs font-bold rounded-t-lg transition-all ${
                      evidenceTab === "request"
                        ? "bg-primary/10 text-primary border-b-2 border-primary"
                        : "text-on-surface-variant hover:text-on-surface"
                    }`}
                  >
                    Request
                  </button>
                )}
                {hasResponse && (
                  <button
                    onClick={() => setEvidenceTab("response")}
                    className={`px-4 py-2 text-xs font-bold rounded-t-lg transition-all ${
                      evidenceTab === "response"
                        ? "bg-primary/10 text-primary border-b-2 border-primary"
                        : "text-on-surface-variant hover:text-on-surface"
                    }`}
                  >
                    Response
                  </button>
                )}
                {hasPayload && (
                  <button
                    onClick={() => setEvidenceTab("payload")}
                    className={`px-4 py-2 text-xs font-bold rounded-t-lg transition-all ${
                      evidenceTab === "payload"
                        ? "bg-primary/10 text-primary border-b-2 border-primary"
                        : "text-on-surface-variant hover:text-on-surface"
                    }`}
                  >
                    Payload
                  </button>
                )}
              </div>

              {/* Tab Content */}
              <div className="space-y-2">
                {evidenceTab === "request" && hasRequest && (
                  <CodeBlock label="HTTP Request" content={evidenceRequest} />
                )}
                {evidenceTab === "response" && hasResponse && (
                  <CodeBlock label="HTTP Response" content={evidenceResponse} />
                )}
                {evidenceTab === "payload" && hasPayload && (
                  <CodeBlock label="Payload" content={evidencePayload} tone="red" />
                )}

                {/* Matched pattern */}
                {!!evidence.matchedPattern && (
                  <div className="text-xs text-on-surface-variant font-mono p-3 bg-surface-container-high rounded-lg border border-outline/10">
                    <span className="font-bold uppercase tracking-wider text-[10px]">Matched Pattern: </span>
                    {String(evidence.matchedPattern)}
                  </div>
                )}
              </div>
            </>
          )}
        </motion.div>

        {/* ═══════════════════════════════════════
           SECTION 3: CLASSIFICATION & SCORING
           ═══════════════════════════════════════ */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="bg-surface-container rounded-2xl border border-outline/20 p-6 space-y-6"
        >
          <h2 className="text-sm font-bold font-headline text-on-surface flex items-center gap-2">
            <AlertTriangle size={16} className="text-primary" />
            Classification & Scoring
          </h2>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* OWASP Category */}
            <div className="space-y-1.5">
              <div className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">OWASP Category</div>
              {finding.owasp_category ? (
                <span className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-mono bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                  {finding.owasp_category}
                </span>
              ) : (
                <span className="text-xs text-on-surface-variant italic">N/A</span>
              )}
            </div>

            {/* CWE */}
            <div className="space-y-1.5">
              <div className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">CWE ID</div>
              {finding.cwe_id ? (
                <a
                  href={`https://cwe.mitre.org/data/definitions/${finding.cwe_id.replace("CWE-", "")}.html`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-mono bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 hover:bg-cyan-500/20 transition-colors"
                >
                  {finding.cwe_id}
                  <ExternalLink size={10} />
                </a>
              ) : (
                <span className="text-xs text-on-surface-variant italic">N/A</span>
              )}
            </div>

            {/* CVSS Score */}
            <div className="space-y-1.5">
              <div className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">
                {finding.cvss_score && finding.source_tool === "nvd" ? "CVSS (NVD)" : "CVSS Score"}
              </div>
              {finding.cvss_score != null ? (
                <span className={`inline-flex items-center px-2.5 py-1.5 rounded-lg text-xs font-mono font-bold border ${cvssColor(finding.cvss_score)}`}>
                  {finding.cvss_score.toFixed(1)}
                </span>
              ) : (
                <span className="text-xs text-on-surface-variant italic">Not calculated</span>
              )}
            </div>

            {/* Source Tool */}
            <div className="space-y-1.5">
              <div className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Source Tool</div>
              <span className="inline-flex items-center px-2.5 py-1.5 rounded-lg text-xs font-mono bg-surface-container-high text-on-surface border border-outline/20">
                {finding.source_tool}
              </span>
            </div>
          </div>

          {/* Confidence Bar */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            <ProgressBar value={finding.confidence || 0} label="Confidence" color="bg-primary" />

            {/* FP Likelihood */}
            <div className="space-y-1.5">
              <div className="flex justify-between text-[10px] font-mono text-on-surface-variant">
                <span>False Positive Likelihood</span>
                <span>{finding.fp_likelihood != null ? `${(finding.fp_likelihood * 100).toFixed(0)}%` : "N/A"}</span>
              </div>
              <div className="w-full h-2 bg-surface-container-high rounded-full overflow-hidden">
                {finding.fp_likelihood != null && (
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${
                      finding.fp_likelihood >= 0.5 ? "bg-amber-500" : "bg-green-500"
                    }`}
                    style={{ width: `${Math.min(finding.fp_likelihood * 100, 100)}%` }}
                  />
                )}
              </div>
              {finding.fp_likelihood != null && finding.fp_likelihood >= 0.5 && (
                <p className="text-[10px] text-amber-500 flex items-center gap-1">
                  <AlertTriangle size={10} />
                  High false-positive likelihood — manual verification recommended
                </p>
              )}
            </div>
          </div>
        </motion.div>

        {/* ═══════════════════════════════════════
           SECTION 4: REPRODUCTION STEPS
           ═══════════════════════════════════════ */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15 }}
          className="bg-surface-container rounded-2xl border border-outline/20 p-6 space-y-4"
        >
          <h2 className="text-sm font-bold font-headline text-on-surface flex items-center gap-2">
            <ChevronRight size={16} className="text-primary" />
            Reproduction Steps
          </h2>

          {reproSteps.length > 0 ? (
            <ol className="list-decimal list-inside space-y-2">
              {reproSteps.map((step, i) => (
                <li key={i} className="text-sm font-body text-on-surface leading-relaxed pl-2">
                  {step}
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-xs text-on-surface-variant italic">No reproduction steps recorded.</p>
          )}
        </motion.div>

        {/* ═══════════════════════════════════════
           SECTION 5: AI EXPLANATION
           ═══════════════════════════════════════ */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="bg-surface-container rounded-2xl border border-outline/20 p-6 space-y-4"
        >
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold font-headline text-on-surface flex items-center gap-2">
              <Sparkles size={16} className="text-primary" />
              AI Explanation
            </h2>
            {!aiExplanation && !aiLoading && (
              <button
                onClick={handleAiExplain}
                className="flex items-center gap-2 px-4 py-2 text-xs font-bold bg-primary text-white rounded-xl hover:bg-primary/90 transition-all"
              >
                <Sparkles size={14} />
                Explain with AI
              </button>
            )}
          </div>

          {aiLoading && (
            <div className="animate-pulse space-y-3">
              <div className="h-4 bg-surface-container-high rounded w-3/4" />
              <div className="h-4 bg-surface-container-high rounded w-1/2" />
              <div className="h-4 bg-surface-container-high rounded w-5/6" />
              <div className="h-4 bg-surface-container-high rounded w-2/3" />
            </div>
          )}

          {aiError && (
            <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-500">
              {aiError}
            </div>
          )}

          {aiExplanation && !aiLoading && (
            <div className="space-y-4 text-sm text-on-surface leading-relaxed">
              {aiExplanation.summary && (
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-primary mb-1">Summary</h3>
                  <p>{aiExplanation.summary}</p>
                </div>
              )}
              {aiExplanation.impact && (
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-red-400 mb-1">Impact</h3>
                  <p>{aiExplanation.impact}</p>
                </div>
              )}
              {aiExplanation.fix && (
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-green-400 mb-1">Fix Guidance</h3>
                  <p className="whitespace-pre-wrap">{aiExplanation.fix}</p>
                </div>
              )}
              {aiExplanation.developer_story && (
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-cyan-400 mb-1">Developer Story</h3>
                  <p>{aiExplanation.developer_story}</p>
                </div>
              )}
            </div>
          )}

          {!aiExplanation && !aiLoading && !aiError && (
            <p className="text-xs text-on-surface-variant italic">
              Click "Explain with AI" to get an AI-powered analysis of this finding.
            </p>
          )}
        </motion.div>
      </div>
    </div>
  );
}
