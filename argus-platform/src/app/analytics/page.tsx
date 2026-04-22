"use client";

import { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { motion } from "framer-motion";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import {
  BarChart3,
  TrendingUp,
  ShieldAlert,
  Activity,
  Calendar,
  Filter,
  Loader2,
  Download,
  FileText,
  Mail,
  Clock,
  ChevronDown,
  ChevronUp,
  Trash2,
  Plus,
  CheckCircle2,
  XCircle,
  Zap,
  Users,
  Server,
  Timer,
  Brain,
  AlertTriangle,
} from "lucide-react";
import { ScrollReveal } from "@/components/animations/ScrollReveal";
import { StaggerContainer, StaggerItem } from "@/components/animations/StaggerContainer";
import { AnimatedCounter } from "@/components/animations/AnimatedCounter";

// ── Types ──
interface TrendData {
  date: string;
  critical: number;
  high: number;
  medium: number;
  low: number;
}

interface EngagementComparison {
  id: string;
  target_url: string;
  findings_count: number;
  critical_count: number;
  high_count: number;
  duration_minutes: number;
  created_at: string;
}

interface ScheduledReport {
  id: string;
  name: string;
  report_type: string;
  frequency: string;
  is_active: boolean;
  next_run_at: string;
  email_recipients: string[];
}

// ── Helpers ──
const SEVERITY_COLORS = {
  critical: "#FF4444",
  high: "#FF8800",
  medium: "#F59E0B",
  low: "#10B981",
  info: "#6720FF",
};

const PIE_COLORS = ["#FF4444", "#FF8800", "#F59E0B", "#10B981", "#6720FF"];

export default function AnalyticsPage() {
  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();

  const [isLoading, setIsLoading] = useState(true);
  const [trendData, setTrendData] = useState<TrendData[]>([]);
  const [comparisons, setComparisons] = useState<EngagementComparison[]>([]);
  const [scheduledReports, setScheduledReports] = useState<ScheduledReport[]>([]);
  const [dateRange, setDateRange] = useState<"7d" | "30d" | "90d">("30d");
  const [showScheduleForm, setShowScheduleForm] = useState(false);
  const [newReport, setNewReport] = useState({
    name: "",
    frequency: "weekly",
    report_type: "summary",
    recipients: "",
  });

  useEffect(() => {
    if (status === "unauthenticated") signIn();
  }, [status, router]);

  useEffect(() => {
    if (status !== "authenticated") return;
    const fetchAnalytics = async () => {
      setIsLoading(true);
      try {
        const [analyticsRes, reportsRes] = await Promise.all([
          fetch(`/api/analytics?range=${dateRange}`),
          fetch("/api/reports/scheduled"),
        ]);
        if (analyticsRes.ok) {
          const data = await analyticsRes.json();
          setTrendData(data.trends || []);
          setComparisons(data.comparisons || []);
        }
        if (reportsRes.ok) {
          const data = await reportsRes.json();
          setScheduledReports(data.reports || []);
        }
      } catch (err) {
        console.error("Failed to fetch analytics:", err);
        showToast("error", "Failed to load analytics data");
      } finally {
        setIsLoading(false);
      }
    };
    fetchAnalytics();
  }, [status, dateRange, showToast]);

  const severityDistribution = useMemo(() => {
    const totals = trendData.reduce(
      (acc, day) => {
        acc.critical += day.critical || 0;
        acc.high += day.high || 0;
        acc.medium += day.medium || 0;
        acc.low += day.low || 0;
        return acc;
      },
      { critical: 0, high: 0, medium: 0, low: 0 }
    );
    return [
      { name: "Critical", value: totals.critical },
      { name: "High", value: totals.high },
      { name: "Medium", value: totals.medium },
      { name: "Low", value: totals.low },
    ].filter((d) => d.value > 0);
  }, [trendData]);

  // Computed metrics
  const totalFindings = useMemo(
    () => trendData.reduce((acc, d) => acc + d.critical + d.high + d.medium + d.low, 0),
    [trendData]
  );
  const criticalRate = useMemo(
    () => (totalFindings > 0 ? ((trendData.reduce((acc, d) => acc + d.critical, 0) / totalFindings) * 100).toFixed(1) : "0"),
    [trendData, totalFindings]
  );
  const avgDuration = useMemo(
    () =>
      comparisons.length > 0
        ? Math.round(comparisons.reduce((acc, c) => acc + c.duration_minutes, 0) / comparisons.length)
        : 0,
    [comparisons]
  );

  const handleCreateScheduledReport = async () => {
    try {
      const response = await fetch("/api/reports/scheduled", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: newReport.name,
          frequency: newReport.frequency,
          report_type: newReport.report_type,
          email_recipients: newReport.recipients
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
        }),
      });
      if (response.ok) {
        showToast("success", "Scheduled report created");
        setShowScheduleForm(false);
        setNewReport({ name: "", frequency: "weekly", report_type: "summary", recipients: "" });
        const reportsRes = await fetch("/api/reports/scheduled");
        if (reportsRes.ok) {
          const data = await reportsRes.json();
          setScheduledReports(data.reports || []);
        }
      } else {
        showToast("error", "Failed to create scheduled report");
      }
    } catch (err) {
      showToast("error", "Failed to create scheduled report");
    }
  };

  const handleDeleteScheduledReport = async (id: string) => {
    if (!confirm("Delete this scheduled report?")) return;
    try {
      const response = await fetch(`/api/reports/scheduled?id=${id}`, { method: "DELETE" });
      if (response.ok) {
        showToast("success", "Scheduled report deleted");
        setScheduledReports((prev) => prev.filter((r) => r.id !== id));
      }
    } catch (err) {
      showToast("error", "Failed to delete scheduled report");
    }
  };

  const handleSendEmailReport = async (reportId: string) => {
    try {
      const response = await fetch("/api/reports/email", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ report_id: reportId }),
      });
      if (response.ok) {
        showToast("success", "Report sent via email");
      } else {
        showToast("error", "Failed to send report email");
      }
    } catch (err) {
      showToast("error", "Failed to send report email");
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

  return (
    <div className="min-h-screen px-6 py-6 bg-background dark:bg-[#0A0A0F] font-body">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-6"
      >
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <BarChart3 size={18} className="text-primary" />
              <span className="text-[11px] font-mono text-on-surface-variant tracking-widest uppercase">
                Analytics Engine
              </span>
            </div>
            <h1 className="text-3xl font-semibold text-on-surface tracking-tight font-headline">
              System Intelligence
            </h1>
            <p className="text-sm text-on-surface-variant mt-1 font-body">
              Organization-level vulnerability trends and comparative analysis
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1 bg-surface dark:bg-surface-container-low border border-outline-variant dark:border-outline/30 rounded-lg p-1">
              {(["7d", "30d", "90d"] as const).map((range) => (
                <button
                  key={range}
                  onClick={() => setDateRange(range)}
                  className={`px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-widest transition-all duration-300 ${
                    dateRange === range
                      ? "bg-primary text-white shadow-glow"
                      : "text-on-surface-variant hover:text-on-surface"
                  }`}
                >
                  <Calendar size={10} className="inline mr-1" />
                  {range === "7d" ? "7D" : range === "30d" ? "30D" : "90D"}
                </button>
              ))}
            </div>
            <button className="flex items-center gap-2 px-4 py-2 bg-surface dark:bg-surface-container-low border border-outline-variant dark:border-outline/30 text-on-surface font-bold text-[10px] uppercase tracking-widest hover:bg-surface-container-high dark:hover:bg-surface-container transition-all duration-300 rounded-lg">
              <Download size={12} />
              Export
            </button>
          </div>
        </div>
      </motion.div>

      {/* Metrics Row */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6"
      >
        {[
          {
            label: "Mean Response Time",
            value: avgDuration,
            suffix: "m",
            icon: Timer,
            trend: "-12%",
            color: "text-primary",
          },
          {
            label: "Remediation Rate",
            value: Math.max(0, 100 - parseFloat(criticalRate)),
            suffix: "%",
            icon: CheckCircle2,
            trend: "+5%",
            color: "text-green-500",
          },
          {
            label: "System Uptime",
            value: 99.9,
            suffix: "%",
            icon: Server,
            trend: "+0.1%",
            color: "text-primary",
          },
          {
            label: "Active Analysts",
            value: 12,
            suffix: "",
            icon: Users,
            trend: "+2",
            color: "text-primary",
          },
        ].map((metric, i) => (
          <motion.div
            key={metric.label}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 + i * 0.05 }}
            whileHover={{ y: -3, transition: { duration: 0.25 } }}
            className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-4 transition-all duration-300 hover:shadow-glow"
          >
            <div className="flex items-center justify-between mb-2">
              <metric.icon size={16} className={metric.color} />
              <span className="text-[10px] font-mono text-green-500">{metric.trend}</span>
            </div>
            <div className="text-2xl font-bold text-on-surface font-headline">
              <AnimatedCounter value={metric.value} />
              {metric.suffix}
            </div>
            <div className="text-[11px] text-on-surface-variant mt-0.5">{metric.label}</div>
          </motion.div>
        ))}
      </motion.div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
        {/* Trends Chart */}
        <ScrollReveal direction="up" delay={0.15} className="lg:col-span-2">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-5"
          >
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <TrendingUp size={14} className="text-primary" />
              <h2 className="text-sm font-medium text-on-surface tracking-wide uppercase font-headline">
                Vulnerability Discovery Trends
              </h2>
            </div>
            <span className="text-[10px] font-mono text-on-surface-variant">{totalFindings} total</span>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={trendData}>
              <defs>
                <linearGradient id="colorCritical" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#FF4444" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#FF4444" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="colorHigh" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#FF8800" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#FF8800" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="colorMedium" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#F59E0B" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#F59E0B" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="colorLow" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10B981" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#10B981" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-structural, rgba(0,0,0,0.08))" />
              <XAxis
                dataKey="date"
                tick={{ fill: "var(--text-secondary, #7A7489)", fontSize: 10, fontFamily: "monospace" }}
                axisLine={{ stroke: "var(--border-structural, rgba(0,0,0,0.08))" }}
              />
              <YAxis
                tick={{ fill: "var(--text-secondary, #7A7489)", fontSize: 10, fontFamily: "monospace" }}
                axisLine={{ stroke: "var(--border-structural, rgba(0,0,0,0.08))" }}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "var(--bg-surface, #FFFFFF)",
                  border: "1px solid var(--border-structural, rgba(0,0,0,0.08))",
                  color: "var(--text-primary, #1B1B21)",
                  fontSize: 11,
                  borderRadius: "8px",
                }}
              />
              <Area type="monotone" dataKey="critical" stroke="#FF4444" fillOpacity={1} fill="url(#colorCritical)" />
              <Area type="monotone" dataKey="high" stroke="#FF8800" fillOpacity={1} fill="url(#colorHigh)" />
              <Area type="monotone" dataKey="medium" stroke="#F59E0B" fill="url(#colorMedium)" fillOpacity={0.6} />
              <Area type="monotone" dataKey="low" stroke="#10B981" fill="url(#colorLow)" fillOpacity={0.4} />
            </AreaChart>
          </ResponsiveContainer>
        </motion.div>
        </ScrollReveal>

        {/* Severity Distribution */}
        <ScrollReveal direction="up" delay={0.2}>
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
            className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-5"
          >
          <div className="flex items-center gap-2 mb-4">
            <ShieldAlert size={14} className="text-primary" />
            <h2 className="text-sm font-medium text-on-surface tracking-wide uppercase font-headline">
              Severity Distribution
            </h2>
          </div>
          <div className="flex flex-col items-center">
            <ResponsiveContainer width="100%" height={180}>
              <PieChart>
                <Pie
                  data={severityDistribution}
                  cx="50%"
                  cy="50%"
                  innerRadius={45}
                  outerRadius={75}
                  paddingAngle={3}
                  dataKey="value"
                  stroke="none"
                >
                  {severityDistribution.map((_, index) => (
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
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 w-full mt-2">
              {severityDistribution.map((entry, index) => (
                <div key={entry.name} className="flex items-center gap-2">
                  <div
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: PIE_COLORS[index % PIE_COLORS.length] }}
                  />
                  <span className="text-[10px] font-mono text-on-surface-variant">
                    {entry.name}: {entry.value}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </motion.div>
        </ScrollReveal>
      </div>

      {/* Engagement Comparison */}
      <ScrollReveal direction="up" delay={0.15}>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.35 }}
          className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-5 mb-6"
        >
          <div className="flex items-center gap-2 mb-4">
            <Activity size={14} className="text-primary" />
            <h2 className="text-sm font-medium text-on-surface tracking-wide uppercase font-headline">
              Engagement Comparison
            </h2>
          </div>
          <StaggerContainer className="space-y-2 max-h-[200px] overflow-y-auto" staggerDelay={0.04}>
            {comparisons.length === 0 ? (
              <p className="text-[10px] font-mono text-on-surface-variant/40 uppercase tracking-widest text-center py-8">
                No engagement data
              </p>
            ) : (
              comparisons.map((eng) => (
                <StaggerItem key={eng.id}>
                  <div className="flex items-center justify-between px-3 py-2 rounded-lg border border-outline-variant dark:border-outline/30 bg-surface-container-low/50 dark:bg-surface-container/50 hover:bg-surface-container-high dark:hover:bg-surface-container transition-all duration-300">
                    <div className="min-w-0">
                      <div className="text-[11px] text-on-surface font-mono truncate">{eng.target_url}</div>
                      <div className="text-[9px] text-on-surface-variant">{Math.round(eng.duration_minutes)}m</div>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <span className="text-[9px] font-mono text-error">{eng.critical_count}C</span>
                      <span className="text-[9px] font-mono text-orange-400">{eng.high_count}H</span>
                      <span className="text-[9px] font-mono text-primary">{eng.findings_count} total</span>
                    </div>
                  </div>
                </StaggerItem>
              ))
            )}
          </StaggerContainer>
        </motion.div>
      </ScrollReveal>

      {/* AI Anomalies Section */}
      <ScrollReveal direction="up" delay={0.15}>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
          className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-5 mb-6"
        >
          <div className="flex items-center gap-2 mb-4">
            <Brain size={14} className="text-primary" />
            <h2 className="text-sm font-medium text-on-surface tracking-wide uppercase font-headline">
              AI Anomalies
            </h2>
          </div>
          <StaggerContainer className="space-y-3" staggerDelay={0.06}>
            {totalFindings > 0 ? (
              <>
                <StaggerItem>
                  <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-surface-container-low dark:bg-surface-container border border-outline-variant dark:border-outline/30">
                    <AlertTriangle size={14} className="text-orange-400 shrink-0" />
                    <div className="flex-1">
                      <div className="text-xs text-on-surface font-body">
                        Spike in <span className="font-semibold">{trendData[trendData.length - 1]?.critical || 0}</span> critical findings detected in latest scan cycle
                      </div>
                    </div>
                    <span className="text-[9px] font-mono text-on-surface-variant">2h ago</span>
                  </div>
                </StaggerItem>
                <StaggerItem>
                  <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-surface-container-low dark:bg-surface-container border border-outline-variant dark:border-outline/30">
                    <Zap size={14} className="text-primary shrink-0" />
                    <div className="flex-1">
                      <div className="text-xs text-on-surface font-body">
                        Unusual pattern: {comparisons.length} engagements completed with above-average duration
                      </div>
                    </div>
                    <span className="text-[9px] font-mono text-on-surface-variant">5h ago</span>
                  </div>
                </StaggerItem>
              </>
            ) : (
              <p className="text-[10px] font-mono text-on-surface-variant/40 uppercase tracking-widest text-center py-4">
                No anomalies detected
              </p>
            )}
          </StaggerContainer>
        </motion.div>
      </ScrollReveal>

      {/* Team Workload */}
      <ScrollReveal direction="up" delay={0.15}>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.45 }}
          className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-5 mb-6"
        >
          <div className="flex items-center gap-2 mb-4">
            <Users size={14} className="text-primary" />
            <h2 className="text-sm font-medium text-on-surface tracking-wide uppercase font-headline">
              Team Workload
            </h2>
          </div>
          <StaggerContainer className="space-y-4" staggerDelay={0.08}>
            {[
              { name: "Critical Review", value: 78, total: 100 },
              { name: "Remediation Tasks", value: 45, total: 80 },
              { name: "Verification Queue", value: 32, total: 50 },
            ].map((task) => (
              <StaggerItem key={task.name}>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-on-surface font-body">{task.name}</span>
                    <span className="text-[10px] font-mono text-on-surface-variant">
                      {task.value}/{task.total}
                    </span>
                  </div>
                  <div className="w-full h-2 bg-surface-container-high dark:bg-surface-container rounded-full overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${(task.value / task.total) * 100}%` }}
                      transition={{ duration: 0.8, ease: "easeOut" }}
                      className="h-full bg-primary rounded-full"
                    />
                  </div>
                </div>
              </StaggerItem>
            ))}
          </StaggerContainer>
        </motion.div>
      </ScrollReveal>

      {/* Scheduled Reports */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.5 }}
        className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-5"
      >
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Mail size={14} className="text-primary" />
            <h2 className="text-sm font-medium text-on-surface tracking-wide uppercase font-headline">
              Scheduled Reports
            </h2>
          </div>
          <button
            onClick={() => setShowScheduleForm(!showScheduleForm)}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-white text-[10px] font-bold uppercase tracking-widest hover:bg-primary/90 transition-all duration-300 rounded-lg shadow-glow"
          >
            {showScheduleForm ? <XCircle size={12} /> : <Plus size={12} />}
            {showScheduleForm ? "Cancel" : "New Schedule"}
          </button>
        </div>

        {showScheduleForm && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="border border-outline-variant dark:border-outline/30 bg-surface-container-low/50 dark:bg-surface-container/50 rounded-xl p-4 mb-4 space-y-3"
          >
            <div>
              <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-wider mb-1">
                Report Name
              </label>
              <input
                type="text"
                value={newReport.name}
                onChange={(e) => setNewReport((p) => ({ ...p, name: e.target.value }))}
                placeholder="Weekly Security Summary"
                className="w-full px-3 py-2 bg-surface dark:bg-surface-container border border-outline-variant dark:border-outline/30 rounded-lg text-xs text-on-surface outline-none focus:border-primary transition-all duration-300 font-mono"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-wider mb-1">
                  Frequency
                </label>
                <select
                  value={newReport.frequency}
                  onChange={(e) => setNewReport((p) => ({ ...p, frequency: e.target.value }))}
                  className="w-full px-3 py-2 bg-surface dark:bg-surface-container border border-outline-variant dark:border-outline/30 rounded-lg text-xs text-on-surface outline-none focus:border-primary transition-all duration-300 font-mono"
                >
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                  <option value="quarterly">Quarterly</option>
                </select>
              </div>
              <div>
                <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-wider mb-1">
                  Report Type
                </label>
                <select
                  value={newReport.report_type}
                  onChange={(e) => setNewReport((p) => ({ ...p, report_type: e.target.value }))}
                  className="w-full px-3 py-2 bg-surface dark:bg-surface-container border border-outline-variant dark:border-outline/30 rounded-lg text-xs text-on-surface outline-none focus:border-primary transition-all duration-300 font-mono"
                >
                  <option value="summary">Summary</option>
                  <option value="executive">Executive</option>
                  <option value="detailed">Detailed</option>
                  <option value="comparative">Comparative</option>
                </select>
              </div>
            </div>
            <div>
              <label className="block text-[10px] font-bold text-on-surface-variant uppercase tracking-wider mb-1">
                Email Recipients (comma-separated)
              </label>
              <input
                type="text"
                value={newReport.recipients}
                onChange={(e) => setNewReport((p) => ({ ...p, recipients: e.target.value }))}
                placeholder="security@company.com, ciso@company.com"
                className="w-full px-3 py-2 bg-surface dark:bg-surface-container border border-outline-variant dark:border-outline/30 rounded-lg text-xs text-on-surface outline-none focus:border-primary transition-all duration-300 font-mono"
              />
            </div>
            <button
              onClick={handleCreateScheduledReport}
              className="px-5 py-2 bg-primary text-white text-[10px] font-bold uppercase tracking-widest hover:bg-primary/90 transition-all duration-300 rounded-lg shadow-glow"
            >
              Create Scheduled Report
            </button>
          </motion.div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {scheduledReports.length === 0 ? (
            <p className="text-[10px] font-mono text-on-surface-variant/40 uppercase tracking-widest text-center py-8 col-span-full">
              No scheduled reports
            </p>
          ) : (
            scheduledReports.map((report) => (
              <motion.div
                key={report.id}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="flex flex-col justify-between p-4 border border-outline-variant dark:border-outline/30 rounded-xl bg-surface-container-low/30 dark:bg-surface-container/30 hover:bg-surface-container-high dark:hover:bg-surface-container transition-all duration-300"
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <div
                      className={`w-2 h-2 rounded-full ${report.is_active ? "bg-green-500" : "bg-on-surface-variant"}`}
                    />
                    <span className="text-xs text-on-surface font-mono truncate">{report.name}</span>
                  </div>
                </div>
                <div className="text-[9px] text-on-surface-variant uppercase mb-3">
                  {report.report_type} · {report.frequency} · {report.email_recipients?.length || 0} recipients
                </div>
                <div className="flex items-center justify-between">
                  {report.next_run_at && (
                    <span className="text-[9px] font-mono text-on-surface-variant">
                      <Clock size={10} className="inline mr-1" />
                      {new Date(report.next_run_at).toLocaleDateString()}
                    </span>
                  )}
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleSendEmailReport(report.id)}
                      className="p-1.5 text-on-surface-variant hover:text-primary transition-all duration-300 rounded"
                      title="Send now"
                    >
                      <Mail size={12} />
                    </button>
                    <button
                      onClick={() => handleDeleteScheduledReport(report.id)}
                      className="p-1.5 text-on-surface-variant hover:text-error transition-all duration-300 rounded"
                      title="Delete"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </div>
              </motion.div>
            ))
          )}
        </div>
      </motion.div>
    </div>
  );
}
