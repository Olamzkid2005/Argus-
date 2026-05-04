"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { motion } from "framer-motion";
import { log } from "@/lib/logger";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import {
  Activity,
  Shield,
  Globe,
  Zap,
  Clock,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Database,
  Server,
  Cpu,
  Wifi,
  Search,
  Brain,
  DollarSign,
  TrendingUp,
  RefreshCw,
  Gauge,
  CircleDot,
} from "lucide-react";
import { AnimatedCounter } from "@/components/animations/AnimatedCounter";

const TOOLS = [
  "nuclei", "httpx", "nmap", "sqlmap", "semgrep", "ffuf", "gitleaks", "nikto",
] as const;

type CircuitState = "closed" | "half_open" | "open";

interface CircuitBreaker {
  tool: string;
  state: CircuitState;
  failure_count: number;
  cooldown_remaining: number;
  last_failure: string | null;
}

interface LLMUsage {
  total_tokens: number;
  total_cost: number;
  budget_total: number;
  budget_used: number;
  models: { model: string; tokens: number; cost: number }[];
}

interface ThreatResult {
  threat_level: string;
  confidence: number;
  findings: string[];
}

const CIRCUIT_COLORS: Record<CircuitState, { bg: string; text: string; border: string; label: string }> = {
  closed: { bg: "bg-green-500/10", text: "text-green-500", border: "border-green-500/30", label: "Operational" },
  half_open: { bg: "bg-yellow-500/10", text: "text-yellow-500", border: "border-yellow-500/30", label: "Degraded" },
  open: { bg: "bg-error/10", text: "text-error", border: "border-error/30", label: "Open" },
};

const PIE_COLORS = ["#6720FF", "#A78BFA", "#10B981", "#FF8800", "#BA1A1A", "#F59E0B", "#EC4899", "#06B6D4"];

function CircuitBreakerCard({ breaker, index }: { breaker: CircuitBreaker; index: number }) {
  const cfg = CIRCUIT_COLORS[breaker.state];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: index * 0.06 }}
      whileHover={{ y: -2, transition: { duration: 0.25 } }}
      className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-6 transition-all duration-300 hover:shadow-glow hover:border-primary/30"
    >
      <div className="flex items-center justify-between mb-4 gap-2 flex-nowrap">
        <div className="flex items-center gap-2 min-w-0">
          <div className={`w-8 h-8 rounded-lg ${cfg.bg} flex items-center justify-center shrink-0`}>
            <Zap size={16} className={cfg.text} />
          </div>
          <span className="text-sm font-bold text-on-surface dark:text-[#F0F0F5] uppercase truncate font-headline">
            {breaker.tool}
          </span>
        </div>
        <span className={`text-[10px] font-mono px-2 py-0.5 rounded-md border shrink-0 whitespace-nowrap ${cfg.bg} ${cfg.text} ${cfg.border}`}>
          {cfg.label}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08] rounded-lg px-3 py-2.5 min-w-0">
          <div className="text-[10px] font-mono text-on-surface-variant dark:text-[#8A8A9E] mb-0.5">
            Failures
          </div>
          <div className="text-xl font-headline font-semibold text-on-surface dark:text-[#F0F0F5]">
            <AnimatedCounter value={breaker.failure_count} />
          </div>
        </div>
        <div className="bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08] rounded-lg px-3 py-2.5 min-w-0">
          <div className="text-[10px] font-mono text-on-surface-variant dark:text-[#8A8A9E] mb-0.5">
            Cooldown
          </div>
          <div className="text-xl font-headline font-semibold text-on-surface dark:text-[#F0F0F5]">
            {breaker.cooldown_remaining > 0 ? (
              <span className="text-yellow-500">{breaker.cooldown_remaining}s</span>
            ) : (
              <span className="text-green-500">—</span>
            )}
          </div>
        </div>
      </div>

      {breaker.last_failure && (
        <div className="mt-3 text-[10px] font-mono text-on-surface-variant dark:text-[#8A8A9E] truncate">
          Last: {new Date(breaker.last_failure).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
        </div>
      )}
    </motion.div>
  );
}

const TOOL_HEALTH_COLORS: Record<string, { bg: string; text: string; border: string; label: string }> = {
  healthy: { bg: "bg-green-500/10", text: "text-green-500", border: "border-green-500/30", label: "Healthy" },
  degraded: { bg: "bg-yellow-500/10", text: "text-yellow-500", border: "border-yellow-500/30", label: "Degraded" },
  down: { bg: "bg-error/10", text: "text-error", border: "border-error/30", label: "Down" },
};

interface ToolHealthData {
  tool_name: string;
  success_rate_24h: number;
  avg_duration_seconds: number;
  total_runs_24h: number;
  last_success_at: string | null;
  consecutive_failures: number;
  status: string;
}

function ToolHealthCard({ tool }: { tool: ToolHealthData }) {
  const cfg = TOOL_HEALTH_COLORS[tool.status] || TOOL_HEALTH_COLORS.healthy;
  const ratePct = (tool.success_rate_24h * 100).toFixed(0);
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className="bg-surface-container rounded-xl border border-outline/20 p-4 space-y-3"
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold font-mono text-on-surface uppercase">{tool.tool_name}</span>
        <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${cfg.bg} ${cfg.text} ${cfg.border} border`}>
          {cfg.label}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-1.5 text-[10px] font-mono text-on-surface-variant">
        <div className="min-w-0">
          <span className="block truncate opacity-60">Success Rate</span>
          <span className="text-sm font-bold text-on-surface">{ratePct}%</span>
        </div>
        <div className="min-w-0">
          <span className="block truncate opacity-60">Runs 24h</span>
          <span className="text-sm font-bold text-on-surface">{tool.total_runs_24h}</span>
        </div>
        <div className="min-w-0">
          <span className="block truncate opacity-60">Avg Duration</span>
          <span className={`text-sm font-bold ${tool.avg_duration_seconds > 30 ? "text-yellow-500" : "text-on-surface"}`}>
            {tool.avg_duration_seconds.toFixed(1)}s
          </span>
        </div>
        <div className="min-w-0">
          <span className="block truncate opacity-60">Consec Fails</span>
          <span className={`text-sm font-bold ${tool.consecutive_failures >= 3 ? "text-error" : "text-on-surface"}`}>
            {tool.consecutive_failures}
          </span>
        </div>
      </div>
      {tool.last_success_at && (
        <div className="text-[9px] font-mono text-on-surface-variant/50">
          Last success: {new Date(tool.last_success_at).toLocaleString()}
        </div>
      )}
    </motion.div>
  );
}

function SystemHealthCard({
  label,
  icon: Icon,
  status,
  detail,
  index,
}: {
  label: string;
  icon: React.ElementType;
  status: "healthy" | "degraded" | "down";
  detail: string;
  index: number;
}) {
  const statusCfg = {
    healthy: { color: "text-green-500", bg: "bg-green-500/10", dot: "bg-green-500" },
    degraded: { color: "text-yellow-500", bg: "bg-yellow-500/10", dot: "bg-yellow-500" },
    down: { color: "text-error", bg: "bg-error/10", dot: "bg-error" },
  }[status];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.3 + index * 0.08 }}
      whileHover={{ y: -2, transition: { duration: 0.25 } }}
      className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-5 transition-all duration-300 hover:shadow-glow"
    >
      <div className="flex items-center gap-3 mb-3">
        <div className={`w-10 h-10 rounded-lg ${statusCfg.bg} flex items-center justify-center`}>
          <Icon size={20} className={statusCfg.color} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-bold text-on-surface dark:text-[#F0F0F5] font-headline">{label}</div>
          <div className="text-[11px] text-on-surface-variant dark:text-[#8A8A9E] font-mono">{detail}</div>
        </div>
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full animate-pulse ${statusCfg.dot}`} />
          <span className={`text-[10px] font-bold uppercase tracking-widest ${statusCfg.color}`}>
            {status}
          </span>
        </div>
      </div>
    </motion.div>
  );
}

export default function SystemHealthPage() {
  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();

  useEffect(() => {
    log.pageMount("SystemHealth");
    return () => log.pageUnmount("SystemHealth");
  }, []);

  const [circuitBreakers, setCircuitBreakers] = useState<CircuitBreaker[]>([]);
  const [llmUsage, setLlmUsage] = useState<LLMUsage | null>(null);
  const [workerHealth, setWorkerHealth] = useState<{ status: string; detail: string }>({ status: "healthy", detail: "All workers online" });
  const [dbHealth, setDbHealth] = useState<{ status: string; detail: string }>({ status: "healthy", detail: "Connected" });
  const [redisHealth, setRedisHealth] = useState<{ status: string; detail: string }>({ status: "healthy", detail: "Connected" });
  const [toolHealth, setToolHealth] = useState<ToolHealthData[]>([]);

  // Threat enrichment state
  const [enrichTarget, setEnrichTarget] = useState("");
  const [enrichType, setEnrichType] = useState<"URL" | "Domain" | "IP">("URL");
  const [isEnriching, setIsEnriching] = useState(false);
  const [threatResult, setThreatResult] = useState<ThreatResult | null>(null);

  // Poll system health data every 5 seconds
  useEffect(() => {
    if (status !== "authenticated") return;

    const fetchHealth = async () => {
      try {
        const res = await fetch("/api/system/health");
        if (res.ok) {
          const data = await res.json();

          const breakers: CircuitBreaker[] = TOOLS.map((tool) => {
            const toolData = data.circuit_breakers?.[tool] || {};
            return {
              tool,
              state: toolData.state || "closed",
              failure_count: toolData.failure_count || 0,
              cooldown_remaining: toolData.cooldown_remaining || 0,
              last_failure: toolData.last_failure || null,
            };
          });
          setCircuitBreakers(breakers);

          if (data.llm_usage) {
            setLlmUsage(data.llm_usage);
          }

          if (data.workers) setWorkerHealth(data.workers);
          if (data.database) setDbHealth(data.database);
          if (data.redis) setRedisHealth(data.redis);
          if (data.tool_health) setToolHealth(data.tool_health);
        }
      } catch (err) {
        console.error("Failed to fetch system health:", err);
      }
    };

    fetchHealth();
    const interval = setInterval(fetchHealth, 5000);
    return () => clearInterval(interval);
  }, [status]);

  // Auth redirect
  useEffect(() => {
    if (status === "unauthenticated") {
      router.push("/auth/signin");
    }
  }, [status, router]);

  const handleEnrich = async () => {
    if (!enrichTarget.trim()) return;
    setIsEnriching(true);
    setThreatResult(null);
    try {
      const res = await fetch("/api/system/enrich", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: enrichTarget, type: enrichType }),
      });
      if (res.ok) {
        const data = await res.json();
        setThreatResult(data);
      } else {
        showToast("error", "Enrichment failed");
      }
    } catch {
      showToast("error", "Enrichment request failed");
    } finally {
      setIsEnriching(false);
    }
  };

  const costDistribution = useMemo(() => {
    if (!llmUsage?.models?.length) return [];
    return llmUsage.models.map((m) => ({ name: m.model, value: m.cost }));
  }, [llmUsage]);

  const budgetPercent = useMemo(() => {
    if (!llmUsage || llmUsage.budget_total === 0) return 0;
    return Math.round((llmUsage.budget_used / llmUsage.budget_total) * 100);
  }, [llmUsage]);

  const threatLevelColor = (level: string) => {
    switch (level?.toLowerCase()) {
      case "critical": return "text-error bg-error/10 border-error/30";
      case "high": return "text-orange-400 bg-orange-400/10 border-orange-400/30";
      case "medium": return "text-yellow-500 bg-yellow-500/10 border-yellow-500/30";
      case "low": return "text-green-500 bg-green-500/10 border-green-500/30";
      default: return "text-on-surface-variant bg-surface-container border-outline-variant";
    }
  };

  if (status === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background dark:bg-[#0A0A0F]">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!session) return null;

  return (
    <div className="min-h-screen px-6 py-6 bg-background dark:bg-[#0A0A0F] font-body pb-24">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-8"
      >
        <div className="flex items-center gap-2 mb-2">
          <Activity size={18} className="text-primary" />
          <span className="text-[11px] font-mono text-on-surface-variant tracking-widest uppercase">
            Infrastructure Monitor
          </span>
        </div>
        <h1 className="text-3xl font-semibold text-on-surface dark:text-white tracking-tight font-headline">
          System Health
        </h1>
        <p className="text-sm text-on-surface-variant mt-1 font-body">
          Circuit breakers, LLM costs, threat enrichment, and infrastructure status
        </p>
      </motion.div>

      <div className="grid grid-cols-12 gap-6">
        {/* ── Left Column: Circuit Breakers + LLM Usage ── */}
        <div className="col-span-12 lg:col-span-8 space-y-6">
          {/* Circuit Breaker Status */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
          >
            <div className="flex items-center gap-2 mb-4">
              <Shield size={16} className="text-primary" />
              <h2 className="text-sm font-bold text-on-surface uppercase tracking-widest font-headline">
                Circuit Breaker Status
              </h2>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {circuitBreakers.map((breaker, i) => (
                <CircuitBreakerCard key={breaker.tool} breaker={breaker} index={i} />
              ))}
            </div>
          </motion.div>

          {/* Tool Health Status */}
          {toolHealth.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.15 }}
            >
              <div className="flex items-center gap-2 mb-4">
                <Activity size={16} className="text-primary" />
                <h2 className="text-sm font-bold text-on-surface uppercase tracking-widest font-headline">
                  Tool Health (24h)
                </h2>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                {toolHealth.map((tool) => (
                  <ToolHealthCard key={tool.tool_name} tool={tool} />
                ))}
              </div>
            </motion.div>
          )}

          {/* LLM Usage & Cost */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-6"
          >
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 flex items-center justify-center rounded-lg bg-purple-500/10 border border-purple-500/20">
                <Brain className="h-5 w-5 text-purple-400" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-on-surface uppercase tracking-widest font-headline">
                  LLM Usage &amp; Cost
                </h2>
                <p className="text-[11px] text-on-surface-variant">Token consumption and budget tracking</p>
              </div>
            </div>

            {/* Summary Stats */}
            <div className="grid grid-cols-2 gap-4 mb-6">
              <div className="bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08] rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Zap size={14} className="text-primary" />
                  <span className="text-[10px] font-mono text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider">
                    Total Tokens
                  </span>
                </div>
                <div className="text-2xl font-headline font-bold text-on-surface dark:text-[#F0F0F5]">
                  <AnimatedCounter value={llmUsage?.total_tokens ?? 0} />
                </div>
              </div>
              <div className="bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08] rounded-lg p-4">
                <div className="flex items-center gap-2 mb-2">
                  <DollarSign size={14} className="text-green-500" />
                  <span className="text-[10px] font-mono text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-wider">
                    Total Cost
                  </span>
                </div>
                <div className="text-2xl font-headline font-bold text-on-surface dark:text-[#F0F0F5]">
                  ${(llmUsage?.total_cost ?? 0).toFixed(4)}
                </div>
              </div>
            </div>

            {/* Budget Remaining Bar */}
            <div className="mb-6">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-bold text-on-surface-variant uppercase tracking-wider font-headline">
                  Budget Remaining
                </span>
                <span className="text-[10px] font-mono text-primary">
                  ${(llmUsage?.budget_used ?? 0).toFixed(2)} / ${(llmUsage?.budget_total ?? 0).toFixed(2)}
                </span>
              </div>
              <div className="w-full h-2 bg-surface-container-high dark:bg-surface-container rounded-full overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${budgetPercent}%` }}
                  transition={{ delay: 0.5, duration: 0.8, ease: "easeOut" }}
                  className={`h-full rounded-full ${budgetPercent > 80 ? "bg-error" : budgetPercent > 60 ? "bg-orange-500" : "bg-primary"}`}
                />
              </div>
              <div className="flex justify-between mt-1">
                <span className="text-[9px] text-on-surface-variant">0%</span>
                <span className="text-[9px] text-on-surface-variant">{budgetPercent}% used</span>
              </div>
            </div>

            {/* Per-Model Breakdown Table */}
            <div className="mb-6">
              <div className="flex items-center gap-2 mb-3">
                <TrendingUp size={12} className="text-on-surface-variant" />
                <span className="text-[11px] font-bold text-on-surface-variant uppercase tracking-wider font-headline">
                  Per-Model Breakdown
                </span>
              </div>
              <div className="border border-outline-variant dark:border-outline/30 rounded-lg overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-surface-container dark:bg-[#1A1A24] border-b border-outline-variant dark:border-[#ffffff08]">
                      <th className="text-left px-4 py-2.5 text-[10px] font-bold text-on-surface-variant uppercase tracking-wider font-headline">
                        Model
                      </th>
                      <th className="text-right px-4 py-2.5 text-[10px] font-bold text-on-surface-variant uppercase tracking-wider font-headline">
                        Tokens
                      </th>
                      <th className="text-right px-4 py-2.5 text-[10px] font-bold text-on-surface-variant uppercase tracking-wider font-headline">
                        Cost
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {(llmUsage?.models ?? []).length === 0 ? (
                      <tr>
                        <td colSpan={3} className="px-4 py-6 text-center text-[10px] font-mono text-on-surface-variant/40 uppercase tracking-widest">
                          No LLM usage recorded
                        </td>
                      </tr>
                    ) : (
                      (llmUsage?.models ?? []).map((m, i) => (
                        <tr
                          key={m.model}
                          className="border-b border-outline-variant dark:border-[#ffffff05] last:border-b-0 hover:bg-surface-container dark:hover:bg-[#1A1A24] transition-colors duration-200"
                        >
                          <td className="px-4 py-2.5 font-mono text-on-surface dark:text-[#F0F0F5]">{m.model}</td>
                          <td className="px-4 py-2.5 text-right font-mono text-on-surface-variant">
                            {m.tokens.toLocaleString()}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-primary">${m.cost.toFixed(4)}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Cost Distribution Pie Chart */}
            {costDistribution.length > 0 && (
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <CircleDot size={12} className="text-on-surface-variant" />
                  <span className="text-[11px] font-bold text-on-surface-variant uppercase tracking-wider font-headline">
                    Cost Distribution
                  </span>
                </div>
                <div className="flex flex-col items-center">
                  <ResponsiveContainer width="100%" height={200}>
                    <PieChart>
                      <Pie
                        data={costDistribution}
                        cx="50%"
                        cy="50%"
                        innerRadius={45}
                        outerRadius={75}
                        paddingAngle={3}
                        dataKey="value"
                        stroke="none"
                      >
                        {costDistribution.map((_, index) => (
                          <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{
                          backgroundColor: "var(--bg-surface, #FFFFFF)",
                          border: "1px solid var(--border-structural, rgba(0,0,0,0.08))",
                          color: "var(--text-primary, #1B1B21)",
                          fontSize: 11,
                          borderRadius: "8px",
                        }}
                        formatter={(value: unknown) => [`$${Number((value as number) ?? 0).toFixed(4)}`, "Cost"]}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 w-full mt-2">
                    {costDistribution.map((entry, index) => (
                      <div key={entry.name} className="flex items-center gap-2">
                        <div
                          className="w-2 h-2 rounded-full shrink-0"
                          style={{ backgroundColor: PIE_COLORS[index % PIE_COLORS.length] }}
                        />
                        <span className="text-[10px] font-mono text-on-surface-variant truncate">
                          {entry.name}: ${entry.value.toFixed(4)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </motion.div>
        </div>

        {/* ── Right Column: Threat Intel + System Metrics ── */}
        <div className="col-span-12 lg:col-span-4 space-y-6">
          {/* Threat Intel Enrichment */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 }}
            className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-6"
          >
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 flex items-center justify-center rounded-lg bg-orange-400/10 border border-orange-400/20">
                <Search className="h-5 w-5 text-orange-400" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-on-surface uppercase tracking-widest font-headline">
                  Threat Intel Enrichment
                </h2>
                <p className="text-[11px] text-on-surface-variant">Lookup indicators of compromise</p>
              </div>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-[11px] font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-[0.2em] mb-2 font-body">
                  Target Indicator
                </label>
                <div className="relative">
                  <Globe className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-on-surface-variant dark:text-[#8A8A9E]" />
                  <input
                    type="text"
                    value={enrichTarget}
                    onChange={(e) => setEnrichTarget(e.target.value)}
                    placeholder="example.com or 192.168.1.1"
                    className="w-full pl-10 pr-4 py-3 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff10] rounded-lg text-sm font-mono text-on-surface dark:text-[#F0F0F5] outline-none focus:border-primary transition-all duration-300 placeholder:text-on-surface-variant/40 dark:placeholder:text-[#8A8A9E]/40"
                  />
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-bold text-on-surface-variant dark:text-[#8A8A9E] uppercase tracking-[0.2em] mb-2 font-body">
                  Indicator Type
                </label>
                <div className="grid grid-cols-3 gap-2">
                  {(["URL", "Domain", "IP"] as const).map((t) => (
                    <button
                      key={t}
                      onClick={() => setEnrichType(t)}
                      className={`py-2 rounded-lg text-[11px] font-bold uppercase tracking-widest transition-all duration-300 border ${
                        enrichType === t
                          ? "border-primary bg-primary/10 text-primary shadow-glow"
                          : "border-outline-variant dark:border-outline/30 bg-surface-container dark:bg-[#1A1A24] text-on-surface-variant hover:border-primary/30"
                      }`}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>

              <button
                onClick={handleEnrich}
                disabled={isEnriching || !enrichTarget.trim()}
                className="w-full flex items-center justify-center gap-2 px-6 py-3 bg-primary text-on-primary text-xs font-bold uppercase tracking-widest rounded-lg hover:opacity-90 transition-all duration-300 shadow-glow disabled:opacity-50"
              >
                {isEnriching ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Search size={14} />
                )}
                {isEnriching ? "Enriching..." : "Enrich"}
              </button>

              {/* Results */}
              {threatResult && (
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="space-y-3 pt-2"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-wider font-headline">
                      Threat Level
                    </span>
                    <span
                      className={`text-[10px] font-mono px-2 py-0.5 rounded-md border ${threatLevelColor(threatResult.threat_level)}`}
                    >
                      {threatResult.threat_level?.toUpperCase() || "UNKNOWN"}
                    </span>
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-wider">
                        Confidence
                      </span>
                      <span className="text-[10px] font-mono text-primary">{threatResult.confidence}%</span>
                    </div>
                    <div className="w-full h-1.5 bg-surface-container-high dark:bg-surface-container rounded-full overflow-hidden">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${threatResult.confidence}%` }}
                        transition={{ duration: 0.6, ease: "easeOut" }}
                        className="h-full bg-primary rounded-full"
                      />
                    </div>
                  </div>

                  {threatResult.findings?.length > 0 && (
                    <div>
                      <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-wider block mb-2">
                        Findings
                      </span>
                      <div className="space-y-1.5 max-h-[150px] overflow-y-auto">
                        {threatResult.findings.map((finding, i) => (
                          <div
                            key={i}
                            className="flex items-start gap-2 px-3 py-2 bg-surface-container dark:bg-[#1A1A24] border border-outline-variant dark:border-[#ffffff08] rounded-lg"
                          >
                            <AlertTriangle size={12} className="text-orange-400 shrink-0 mt-0.5" />
                            <span className="text-[11px] text-on-surface dark:text-[#F0F0F5] font-body">
                              {finding}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </motion.div>
              )}
            </div>
          </motion.div>

          {/* System Metrics */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.25 }}
            className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-6"
          >
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 flex items-center justify-center rounded-lg bg-green-500/10 border border-green-500/20">
                <Server className="h-5 w-5 text-green-500" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-on-surface uppercase tracking-widest font-headline">
                  System Metrics
                </h2>
                <p className="text-[11px] text-on-surface-variant">Infrastructure health</p>
              </div>
            </div>

            <div className="space-y-3">
              <SystemHealthCard
                label="Worker Health"
                icon={Cpu}
                status={workerHealth.status as "healthy" | "degraded" | "down"}
                detail={workerHealth.detail}
                index={0}
              />
              <SystemHealthCard
                label="Database"
                icon={Database}
                status={dbHealth.status as "healthy" | "degraded" | "down"}
                detail={dbHealth.detail}
                index={1}
              />
              <SystemHealthCard
                label="Redis"
                icon={Wifi}
                status={redisHealth.status as "healthy" | "degraded" | "down"}
                detail={redisHealth.detail}
                index={2}
              />
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  );
}
