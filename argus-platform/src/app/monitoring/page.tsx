"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { log } from "@/lib/logger";
import {
  ShieldCheck,
  Activity,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  CheckCircle,
  RefreshCw,
  ArrowRight,
  Eye,
  BarChart3,
  Clock,
  Loader2,
  Globe,
  XCircle,
  Shield,
  ShieldAlert,
  Target,
  LineChart,
} from "lucide-react";
import { ScrollReveal } from "@/components/animations/ScrollReveal";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import SkeletonLoader from "@/components/ui-custom/SkeletonLoader";

interface DiffSummary {
  summary?: {
    new_count: number;
    fixed_count: number;
    regressed_count: number;
    persistent_count: number;
    severity_changed_count: number;
    action_required: boolean;
    total_current: number;
    total_previous: number;
  };
  new?: Array<{ id: string; type: string; severity: string; endpoint: string }>;
  fixed?: Array<{ id: string; type: string; severity: string; endpoint: string }>;
  regressed?: Array<{ id: string; type: string; severity: string; endpoint: string }>;
  severity_changed?: Array<{
    finding: { id: string; type: string; endpoint: string };
    old_severity: string;
    new_severity: string;
  }>;
}

interface TargetProfile {
  total_scans: number;
  last_scan_at: string;
  last_findings_count: number;
  last_diff_summary?: DiffSummary["summary"];
  target_domain: string;
  known_endpoints: string[];
  best_tools: Array<{ tool: string; finding_count: number }>;
  noisy_tools: string[];
  confirmed_finding_types: string[];
}

interface CompliancePosture {
  average_composite_score: number;
  total_engagements: number;
  engagements: Array<{
    engagement_id: string;
    target_url: string;
    composite_score: number;
    total_findings: number;
    trend: string;
    computed_at: string;
    framework_scores?: Record<string, { score: number; total_findings: number; critical_count: number; high_count: number; medium_count: number }>;
  }>;
  severity_counts: Record<string, number>;
  trend: Array<{ day: string; avg_score: number }>;
  framework_averages?: Record<string, number>;
}

const severityBg: Record<string, string> = {
  CRITICAL: "bg-red-500/20 text-red-400",
  HIGH: "bg-orange-500/20 text-orange-400",
  MEDIUM: "bg-yellow-500/20 text-yellow-400",
  LOW: "bg-green-500/20 text-green-400",
  INFO: "bg-gray-500/20 text-gray-400",
};

function PostureScoreBadge({ score, size = "md" }: { score: number; size?: "sm" | "md" | "lg" }) {
  const color =
    score >= 80 ? "text-green-400" :
    score >= 60 ? "text-amber-400" :
    score >= 40 ? "text-orange-400" :
    "text-red-400";
  const bg =
    score >= 80 ? "bg-green-500/10" :
    score >= 60 ? "bg-amber-500/10" :
    score >= 40 ? "bg-orange-500/10" :
    "bg-red-500/10";
  const dims = size === "sm" ? "text-lg w-10 h-10" : size === "lg" ? "text-4xl w-20 h-20" : "text-2xl w-16 h-16";
  return (
    <div className={`${dims} rounded-full ${bg} flex items-center justify-center font-headline font-bold ${color}`}>
      {score}
    </div>
  );
}

function TrendIcon({ trend }: { trend: string }) {
  if (trend === "improving") return <TrendingUp size={14} className="text-green-400" />;
  if (trend === "declining") return <TrendingDown size={14} className="text-red-400" />;
  return <ArrowRight size={14} className="text-on-surface-variant/60" />;
}

export default function MonitoringPage() {
  useEffect(() => {
    log.pageMount("Monitoring");
    return () => log.pageUnmount("Monitoring");
  }, []);

  const router = useRouter();
  const [profiles, setProfiles] = useState<TargetProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDomain, setSelectedDomain] = useState<string | null>(null);
  const [diffData, setDiffData] = useState<DiffSummary | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [error, setError] = useState("");

  // Compliance posture state
  const [posture, setPosture] = useState<CompliancePosture | null>(null);
  const [postureLoading, setPostureLoading] = useState(true);

  const fetchProfiles = useCallback(async () => {
    try {
      const response = await fetch("/api/assets");
      if (!response.ok) throw new Error("Failed to load profiles");
      const data = await response.json();
      const activeTargets = (data.assets || []).filter(
        (a: Record<string, unknown>) => a.asset_type === "domain" && a.risk_level !== "INFO"
      );

      const profilePromises = activeTargets.map(async (asset: Record<string, unknown>) => {
        try {
          const domain = asset.identifier as string;
          const res = await fetch(`/api/monitoring/diff/${asset.id}`);
          if (res.ok) {
            const diff = await res.json();
            return {
              target_domain: domain,
              total_scans: (asset as Record<string, number>)?.total_scans || 0,
              last_scan_at: (asset as Record<string, string>)?.last_scan_at || "",
              last_findings_count: (asset as Record<string, number>)?.last_findings_count || 0,
              last_diff_summary: diff?.summary || null,
              known_endpoints: [],
              best_tools: [],
              noisy_tools: [],
              confirmed_finding_types: [],
            };
          }
        } catch {
          // skip individual profile errors
        }
        return null;
      });

      const results = await Promise.all(profilePromises);
      setProfiles(results.filter(Boolean) as TargetProfile[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load monitoring data");
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchPosture = useCallback(async () => {
    try {
      const response = await fetch("/api/compliance/posture");
      if (response.ok) {
        const data = await response.json();
        setPosture(data);
      }
    } catch {
      // Non-critical
    } finally {
      setPostureLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProfiles();
    fetchPosture();
    const interval = setInterval(() => {
      fetchProfiles();
      fetchPosture();
    }, 30000);
    return () => clearInterval(interval);
  }, [fetchProfiles, fetchPosture]);

  const loadDiff = async (assetIdOrDomain: string, domain: string) => {
    setSelectedDomain(domain);
    setDiffLoading(true);
    setDiffData(null);
    try {
      const response = await fetch(`/api/monitoring/diff/${assetIdOrDomain}`);
      if (!response.ok) throw new Error("Failed to load diff");
      const data = await response.json();
      setDiffData(data);
    } catch (err) {
      setDiffData(null);
    } finally {
      setDiffLoading(false);
    }
  };

  if (loading) {
    return <SkeletonLoader className="min-h-screen" />;
  }

  const totalFindings = posture
    ? Object.values(posture.severity_counts).reduce((a, b) => a + b, 0)
    : 0;

  return (
    <div className="min-h-screen bg-background dark:bg-[#0A0A0F] matrix-grid">
      <div className="max-w-[1440px] mx-auto px-4 sm:px-6 py-8">
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mb-8"
        >
          <div className="flex items-center gap-3 mb-2">
            <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
              <Activity size={18} className="text-primary" />
            </div>
            <span className="text-xs font-body text-on-surface-variant dark:text-[#8A8A9E] tracking-widest uppercase">
              Continuous Monitoring
            </span>
          </div>
          <h1 className="text-4xl font-headline font-semibold text-gray-900 dark:text-[#F0F0F5] tracking-tight">
            Posture Monitoring
          </h1>
          <p className="text-sm font-body text-on-surface-variant dark:text-[#8A8A9E] mt-1">
            Track scan diffs, regressions, and compliance posture changes across targets
          </p>
        </motion.div>

        {error && (
          <div className="mb-6 p-4 rounded-xl bg-error/10 border border-error/20 flex items-center gap-3">
            <AlertTriangle size={18} className="text-error shrink-0" />
            <p className="text-sm text-error">{error}</p>
          </div>
        )}

        {/* ── Compliance Posture Dashboard ── */}
        <ScrollReveal direction="up" delay={0.05}>
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
            className="mb-6 bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-6"
          >
            <div className="flex items-center justify-between mb-5">
              <div className="flex items-center gap-2">
                <ShieldCheck size={18} className="text-primary" />
                <h2 className="text-lg font-headline font-semibold text-on-surface dark:text-[#F0F0F5]">
                  Live Compliance Posture
                </h2>
              </div>
              <button
                onClick={fetchPosture}
                className="p-2 rounded-lg hover:bg-surface-container dark:hover:bg-[#1A1A24] transition-colors"
                title="Refresh"
              >
                <RefreshCw size={14} className="text-on-surface-variant dark:text-[#8A8A9E]" />
              </button>
            </div>

            {postureLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 size={20} className="animate-spin text-primary" />
              </div>
            ) : posture ? (
              <div className="space-y-5">
                {/* Score Row */}
                <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                  <div className="col-span-2 md:col-span-1 flex flex-col items-center justify-center p-4 rounded-xl bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08]">
                    <PostureScoreBadge score={posture.average_composite_score} size="lg" />
                    <span className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant dark:text-[#8A8A9E] mt-2">
                      Composite
                    </span>
                    <span className="text-[9px] text-on-surface-variant/60 mt-0.5">
                      {posture.total_engagements} engagement{posture.total_engagements !== 1 ? "s" : ""}
                    </span>
                  </div>

                  {/* Severity Counts */}
                  <div className="p-3 rounded-lg bg-red-500/5 border border-red-500/10 flex flex-col items-center justify-center">
                    <div className="text-xl font-headline font-bold text-red-400">{posture.severity_counts.CRITICAL || 0}</div>
                    <div className="text-[9px] font-medium text-red-400/70 uppercase tracking-wider mt-0.5">Critical</div>
                  </div>
                  <div className="p-3 rounded-lg bg-orange-500/5 border border-orange-500/10 flex flex-col items-center justify-center">
                    <div className="text-xl font-headline font-bold text-orange-400">{posture.severity_counts.HIGH || 0}</div>
                    <div className="text-[9px] font-medium text-orange-400/70 uppercase tracking-wider mt-0.5">High</div>
                  </div>
                  <div className="p-3 rounded-lg bg-yellow-500/5 border border-yellow-500/10 flex flex-col items-center justify-center">
                    <div className="text-xl font-headline font-bold text-yellow-400">{posture.severity_counts.MEDIUM || 0}</div>
                    <div className="text-[9px] font-medium text-yellow-400/70 uppercase tracking-wider mt-0.5">Medium</div>
                  </div>
                  <div className="p-3 rounded-lg bg-primary/5 border border-primary/10 flex flex-col items-center justify-center">
                    <div className="text-xl font-headline font-bold text-primary">{totalFindings}</div>
                    <div className="text-[9px] font-medium text-primary/70 uppercase tracking-wider mt-0.5">Total</div>
                  </div>
                </div>

                {/* Per-Framework Breakdown */}
                {posture.framework_averages && Object.keys(posture.framework_averages).length > 0 && (
                  <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3">
                    {Object.entries(posture.framework_averages).map(([fw, score]) => {
                      const label = fw.replace(/_/g, " ").toUpperCase();
                      const color = score >= 80 ? "text-green-400 border-green-500/20 bg-green-500/5"
                        : score >= 60 ? "text-amber-400 border-amber-500/20 bg-amber-500/5"
                        : "text-red-400 border-red-500/20 bg-red-500/5";
                      return (
                        <div key={fw} className={`p-3 rounded-xl border ${color}`}>
                          <div className="text-[9px] font-bold uppercase tracking-wider opacity-70">{label}</div>
                          <div className="text-lg font-headline font-bold mt-0.5">{score}</div>
                          <div className="text-[8px] opacity-50 mt-0.5">avg score</div>
                        </div>
                      );
                    })}
                    {/* Per-engagement framework drill-down */}
                    {posture.engagements.filter(e => e.framework_scores).length > 0 && (
                      <details className="col-span-full">
                        <summary className="text-[9px] text-primary cursor-pointer hover:underline font-bold uppercase tracking-wider">
                          Per-engagement framework details
                        </summary>
                        <div className="mt-2 space-y-2 max-h-48 overflow-y-auto">
                          {posture.engagements.filter(e => e.framework_scores).map(eng => (
                            <div key={eng.engagement_id} className="p-2 rounded-lg bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08]">
                              <div className="text-[9px] font-mono text-on-surface-variant truncate mb-1">
                                {eng.target_url?.replace(/^https?:\/\//, "") || "N/A"}
                              </div>
                              <div className="flex gap-2 flex-wrap">
                                {Object.entries(eng.framework_scores || {}).map(([fw, fwData]) => (
                                  <span key={fw} className={`text-[8px] font-mono px-1.5 py-0.5 rounded ${
                                    fwData.score >= 80 ? "bg-green-500/10 text-green-400"
                                      : fwData.score >= 60 ? "bg-amber-500/10 text-amber-400"
                                      : "bg-red-500/10 text-red-400"
                                  }`}>
                                    {fw.replace(/_/g, " ").toUpperCase().slice(0, 8)} {Math.round(fwData.score)}
                                  </span>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                  </div>
                )}

                {/* Trend Chart + Engagements */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {/* Trend Chart */}
                  <div className="md:col-span-2 p-4 rounded-xl bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08]">
                    <div className="flex items-center gap-2 mb-3">
                      <LineChart size={14} className="text-primary" />
                      <span className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant dark:text-[#8A8A9E]">
                        Posture Trend
                      </span>
                    </div>
                    {posture.trend.length > 0 ? (
                      <div className="h-40">
                        <ResponsiveContainer width="100%" height="100%">
                          <AreaChart data={posture.trend} margin={{ top: 5, right: 5, bottom: 0, left: 0 }}>
                            <defs>
                              <linearGradient id="postureGradient" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="#6720FF" stopOpacity={0.3} />
                                <stop offset="95%" stopColor="#6720FF" stopOpacity={0} />
                              </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                            <XAxis
                              dataKey="day"
                              tick={{ fontSize: 9, fill: "#8A8A9E" }}
                              tickFormatter={(v: string) => {
                                const d = new Date(v);
                                return `${d.getMonth() + 1}/${d.getDate()}`;
                              }}
                              axisLine={false}
                              tickLine={false}
                            />
                            <YAxis
                              domain={[0, 100]}
                              tick={{ fontSize: 9, fill: "#8A8A9E" }}
                              axisLine={false}
                              tickLine={false}
                            />
                            <Tooltip
                              contentStyle={{
                                background: "#1A1A24",
                                border: "1px solid rgba(255,255,255,0.08)",
                                borderRadius: "8px",
                                fontSize: "11px",
                              }}
                              labelFormatter={(v: string) => new Date(v).toLocaleDateString()}
                              formatter={(value: number) => [`${value}`, "Score"]}
                            />
                            <Area
                              type="monotone"
                              dataKey="avg_score"
                              stroke="#6720FF"
                              strokeWidth={2}
                              fill="url(#postureGradient)"
                            />
                          </AreaChart>
                        </ResponsiveContainer>
                      </div>
                    ) : (
                      <div className="flex items-center justify-center h-40 text-[10px] text-on-surface-variant/40">
                        No trend data yet — run some scans to see posture over time
                      </div>
                    )}
                  </div>

                  {/* Per-Engagement Scores */}
                  <div className="p-4 rounded-xl bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08]">
                    <div className="flex items-center gap-2 mb-3">
                      <Target size={14} className="text-primary" />
                      <span className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant dark:text-[#8A8A9E]">
                        By Engagement
                      </span>
                    </div>
                    {posture.engagements.length > 0 ? (
                      <div className="space-y-2 max-h-36 overflow-y-auto pr-1">
                        {posture.engagements.map((eng) => (
                          <div
                            key={eng.engagement_id}
                            className="flex items-center justify-between p-2 rounded-lg bg-surface-container-high dark:bg-[#2A2A35]"
                          >
                            <div className="min-w-0 flex-1">
                              <div className="text-[10px] font-mono text-on-surface dark:text-[#F0F0F5] truncate">
                                {eng.target_url?.replace(/^https?:\/\//, "") || "N/A"}
                              </div>
                              <div className="flex items-center gap-1.5 mt-0.5">
                                <TrendIcon trend={eng.trend} />
                                <span className="text-[8px] text-on-surface-variant/60 uppercase tracking-wider">
                                  {eng.trend}
                                </span>
                                <span className="text-[8px] text-on-surface-variant/40 ml-1">
                                  {eng.total_findings} findings
                                </span>
                              </div>
                            </div>
                            <PostureScoreBadge score={Math.round(eng.composite_score)} size="sm" />
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="flex items-center justify-center h-36 text-[10px] text-on-surface-variant/40">
                        No engagements with posture scores yet
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-12 text-on-surface-variant/40 dark:text-[#8A8A9E]/40 gap-3">
                <ShieldAlert size={32} />
                <p className="text-[11px] font-mono uppercase tracking-widest text-center">No compliance posture data yet</p>
                <p className="text-[10px] text-center">Complete a scan to see your compliance posture score</p>
              </div>
            )}
          </motion.div>
        </ScrollReveal>

        {/* Diff Summary Dashboard */}
        <ScrollReveal direction="up" delay={0.1}>
          <div className="grid grid-cols-12 gap-6">
            {/* Target List */}
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
              className="col-span-12 lg:col-span-5 bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-6"
            >
              <div className="flex items-center justify-between mb-5">
                <div className="flex items-center gap-2">
                  <Globe size={18} className="text-primary" />
                  <h2 className="text-lg font-headline font-semibold text-on-surface dark:text-[#F0F0F5]">Monitored Targets</h2>
                </div>
                <button
                  onClick={fetchProfiles}
                  className="p-2 rounded-lg hover:bg-surface-container dark:hover:bg-[#1A1A24] transition-colors"
                  title="Refresh"
                >
                  <RefreshCw size={14} className="text-on-surface-variant dark:text-[#8A8A9E]" />
                </button>
              </div>

              {profiles.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-on-surface-variant/40 dark:text-[#8A8A9E]/40 gap-3">
                  <ShieldCheck size={32} />
                  <p className="text-[11px] font-mono uppercase tracking-widest text-center">No monitored targets yet</p>
                  <p className="text-[10px] text-center">Run scheduled scans to enable continuous monitoring</p>
                </div>
              ) : (
                <div className="space-y-3 max-h-[500px] overflow-y-auto pr-1">
                  {profiles.map((profile, idx) => (
                    <motion.button
                      key={profile.target_domain}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ duration: 0.3, delay: idx * 0.05 }}
                      onClick={() => {
                        loadDiff(profile.target_domain, profile.target_domain);
                      }}
                      className={`w-full text-left p-4 rounded-lg border transition-all duration-300 ${
                        selectedDomain === profile.target_domain
                          ? "border-primary bg-primary/5 shadow-glow"
                          : "border-outline-variant dark:border-[#ffffff08] bg-surface-container dark:bg-[#1A1A24] hover:border-primary/30"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm font-mono text-on-surface dark:text-[#F0F0F5] truncate pr-2">{profile.target_domain}</span>
                        <span className="text-[10px] text-on-surface-variant dark:text-[#8A8A9E] whitespace-nowrap">
                          {profile.total_scans} scan{profile.total_scans !== 1 ? "s" : ""}
                        </span>
                      </div>

                      {profile.last_diff_summary && (
                        <div className="flex gap-2 mt-2">
                          {profile.last_diff_summary.new_count > 0 && (
                            <span className="text-[10px] font-medium bg-red-500/10 text-red-400 px-2 py-0.5 rounded flex items-center gap-1">
                              <TrendingUp size={10} />
                              {profile.last_diff_summary.new_count} new
                            </span>
                          )}
                          {profile.last_diff_summary.fixed_count > 0 && (
                            <span className="text-[10px] font-medium bg-green-500/10 text-green-400 px-2 py-0.5 rounded flex items-center gap-1">
                              <CheckCircle size={10} />
                              {profile.last_diff_summary.fixed_count} fixed
                            </span>
                          )}
                          {profile.last_diff_summary.regressed_count > 0 && (
                            <span className="text-[10px] font-medium bg-amber-500/10 text-amber-400 px-2 py-0.5 rounded flex items-center gap-1">
                              <TrendingDown size={10} />
                              {profile.last_diff_summary.regressed_count} regressed
                            </span>
                          )}
                          {profile.last_diff_summary.action_required && (
                            <span className="text-[10px] font-bold bg-red-500/20 text-red-400 px-2 py-0.5 rounded uppercase">
                              Action
                            </span>
                          )}
                        </div>
                      )}

                      {profile.confirmed_finding_types.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-2">
                          {profile.confirmed_finding_types.slice(0, 4).map((t) => (
                            <span key={t} className="text-[9px] font-mono text-on-surface-variant/60 dark:text-[#8A8A9E]/60 bg-surface-container-high dark:bg-[#2A2A35] px-1.5 py-0.5 rounded">
                              {t}
                            </span>
                          ))}
                          {profile.confirmed_finding_types.length > 4 && (
                            <span className="text-[9px] text-on-surface-variant/40">+{profile.confirmed_finding_types.length - 4}</span>
                          )}
                        </div>
                      )}
                    </motion.button>
                  ))}
                </div>
              )}
            </motion.div>

            {/* Diff Detail Panel */}
            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.5, delay: 0.2 }}
              className="col-span-12 lg:col-span-7 bg-surface-container-lowest dark:bg-[#12121A] border border-outline-variant dark:border-[#ffffff10] rounded-xl p-6 min-h-[400px]"
            >
              <div className="flex items-center gap-2 mb-5">
                <BarChart3 size={18} className="text-primary" />
                <h2 className="text-lg font-headline font-semibold text-on-surface dark:text-[#F0F0F5]">
                  {selectedDomain ? `Diff: ${selectedDomain}` : "Scan Diff Detail"}
                </h2>
              </div>

              {!selectedDomain ? (
                <div className="flex flex-col items-center justify-center py-16 text-on-surface-variant/40 dark:text-[#8A8A9E]/40 gap-3">
                  <BarChart3 size={32} />
                  <p className="text-[11px] font-mono uppercase tracking-widest text-center">Select a target to view diff</p>
                  <p className="text-[10px] text-center">Click a monitored domain to see scan comparison</p>
                </div>
              ) : diffLoading ? (
                <div className="flex items-center justify-center py-16">
                  <Loader2 size={24} className="animate-spin text-primary" />
                </div>
              ) : !diffData?.summary ? (
                <div className="flex flex-col items-center justify-center py-16 text-on-surface-variant/40 dark:text-[#8A8A9E]/40 gap-3">
                  <Clock size={32} />
                  <p className="text-[11px] font-mono uppercase tracking-widest text-center">No diff data yet</p>
                  <p className="text-[10px] text-center">Run a follow-up scan to generate diff data</p>
                </div>
              ) : (
                <div className="space-y-6">
                  {/* Summary Grid */}
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                    <div className="p-3 rounded-lg bg-red-500/5 border border-red-500/10">
                      <div className="text-2xl font-headline font-bold text-red-400">{diffData.summary?.new_count || 0}</div>
                      <div className="text-[10px] font-medium text-red-400/70 uppercase tracking-wider mt-0.5">New</div>
                    </div>
                    <div className="p-3 rounded-lg bg-green-500/5 border border-green-500/10">
                      <div className="text-2xl font-headline font-bold text-green-400">{diffData.summary?.fixed_count || 0}</div>
                      <div className="text-[10px] font-medium text-green-400/70 uppercase tracking-wider mt-0.5">Fixed</div>
                    </div>
                    <div className="p-3 rounded-lg bg-amber-500/5 border border-amber-500/10">
                      <div className="text-2xl font-headline font-bold text-amber-400">{diffData.summary?.regressed_count || 0}</div>
                      <div className="text-[10px] font-medium text-amber-400/70 uppercase tracking-wider mt-0.5">Regressed</div>
                    </div>
                    <div className="p-3 rounded-lg bg-blue-500/5 border border-blue-500/10">
                      <div className="text-2xl font-headline font-bold text-blue-400">{diffData.summary?.persistent_count || 0}</div>
                      <div className="text-[10px] font-medium text-blue-400/70 uppercase tracking-wider mt-0.5">Persistent</div>
                    </div>
                    <div className="p-3 rounded-lg bg-purple-500/5 border border-purple-500/10">
                      <div className="text-2xl font-headline font-bold text-purple-400">{diffData.summary?.severity_changed_count || 0}</div>
                      <div className="text-[10px] font-medium text-purple-400/70 uppercase tracking-wider mt-0.5">Severity Δ</div>
                    </div>
                    <div className="p-3 rounded-lg bg-primary/5 border border-primary/10">
                      <div className="text-2xl font-headline font-bold text-primary">
                        {diffData.summary?.total_current || 0}
                      </div>
                      <div className="text-[10px] font-medium text-primary/70 uppercase tracking-wider mt-0.5">Total Current</div>
                    </div>
                  </div>

                  {/* New Findings */}
                  {Array.isArray(diffData.new) && diffData.new.length > 0 && (
                    <div>
                      <h3 className="flex items-center gap-2 text-sm font-semibold text-red-400 mb-3">
                        <TrendingUp size={14} />
                        New Findings ({diffData.new.length})
                      </h3>
                      <div className="space-y-2 max-h-[250px] overflow-y-auto">
                        {diffData.new.map((f, i) => (
                          <div key={i} className="p-3 rounded-lg bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08] flex items-center justify-between">
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-mono text-on-surface dark:text-[#F0F0F5] truncate">{f.type}</span>
                                <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${severityBg[f.severity] || severityBg.INFO}`}>
                                  {f.severity}
                                </span>
                              </div>
                              <p className="text-[10px] text-on-surface-variant/60 dark:text-[#8A8A9E]/60 mt-0.5 truncate">{f.endpoint}</p>
                            </div>
                            <button
                              onClick={() => router.push(`/findings/${f.id}`)}
                              className="p-1.5 text-on-surface-variant/40 hover:text-primary transition-colors shrink-0 ml-2"
                            >
                              <Eye size={14} />
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Regressed Findings */}
                  {Array.isArray(diffData.regressed) && diffData.regressed.length > 0 && (
                    <div>
                      <h3 className="flex items-center gap-2 text-sm font-semibold text-amber-400 mb-3">
                        <TrendingDown size={14} />
                        Regressed ({diffData.regressed.length})
                      </h3>
                      <div className="space-y-2 max-h-[200px] overflow-y-auto">
                        {diffData.regressed.map((f, i) => (
                          <div key={i} className="p-3 rounded-lg bg-amber-500/5 border border-amber-500/10 flex items-center justify-between">
                            <div className="min-w-0">
                              <span className="text-xs font-mono text-on-surface dark:text-[#F0F0F5]">{f.type}</span>
                              <p className="text-[10px] text-on-surface-variant/60 dark:text-[#8A8A9E]/60 mt-0.5 truncate">{f.endpoint}</p>
                            </div>
                            <span className="text-[10px] font-bold text-amber-400 uppercase tracking-wider">⚠ Previously Fixed</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {!diffData.summary?.action_required && (
                    <div className="flex items-center gap-2 p-3 rounded-lg bg-green-500/5 border border-green-500/10">
                      <CheckCircle size={14} className="text-green-400" />
                      <span className="text-xs font-medium text-green-400">No action required — posture unchanged</span>
                    </div>
                  )}
                </div>
              )}
            </motion.div>
          </div>
        </ScrollReveal>
      </div>
    </div>
  );
}
