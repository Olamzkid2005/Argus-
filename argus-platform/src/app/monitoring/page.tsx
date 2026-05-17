"use client";

import { useState, useEffect } from "react";
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
} from "lucide-react";
import { ScrollReveal } from "@/components/animations/ScrollReveal";
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

const severityBg: Record<string, string> = {
  CRITICAL: "bg-red-500/20 text-red-400",
  HIGH: "bg-orange-500/20 text-orange-400",
  MEDIUM: "bg-yellow-500/20 text-yellow-400",
  LOW: "bg-green-500/20 text-green-400",
  INFO: "bg-gray-500/20 text-gray-400",
};

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

  const fetchProfiles = async () => {
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
  };

  useEffect(() => {
    fetchProfiles();
    const interval = setInterval(fetchProfiles, 30000);
    return () => clearInterval(interval);
  }, []);

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
            Track scan diffs, regressions, and security posture changes across targets
          </p>
        </motion.div>

        {error && (
          <div className="mb-6 p-4 rounded-xl bg-error/10 border border-error/20 flex items-center gap-3">
            <AlertTriangle size={18} className="text-error shrink-0" />
            <p className="text-sm text-error">{error}</p>
          </div>
        )}

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
