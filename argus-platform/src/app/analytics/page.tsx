"use client";

import { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
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
} from "lucide-react";

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
  medium: "var(--prism-cream)",
  low: "var(--prism-cyan)",
  info: "var(--text-secondary)",
};

const PIE_COLORS = ["#FF4444", "#FF8800", "var(--prism-cream)", "var(--prism-cyan)", "var(--text-secondary)"];

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
  const [newReport, setNewReport] = useState({ name: "", frequency: "weekly", report_type: "summary", recipients: "" });

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

  const handleCreateScheduledReport = async () => {
    try {
      const response = await fetch("/api/reports/scheduled", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: newReport.name,
          frequency: newReport.frequency,
          report_type: newReport.report_type,
          email_recipients: newReport.recipients.split(",").map((s) => s.trim()).filter(Boolean),
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
          <BarChart3 size={18} className="text-prism-cream" />
          <span className="text-[11px] font-mono text-text-secondary tracking-widest uppercase">Analytics Engine</span>
        </div>
        <h1 className="text-4xl font-semibold text-text-primary tracking-tight">ANALYTICS</h1>
        <p className="text-sm text-text-secondary mt-2">
          Organization-level vulnerability trends and comparative analysis
        </p>
      </div>

      {/* Date Range Filter */}
      <div className="flex items-center gap-3 mb-6">
        {(["7d", "30d", "90d"] as const).map((range) => (
          <button
            key={range}
            onClick={() => setDateRange(range)}
            className={`px-4 py-2 border text-[10px] font-bold uppercase tracking-widest transition-all ${
              dateRange === range
                ? "border-prism-cream/40 bg-surface/50 text-text-primary"
                : "border-structural bg-surface/30 text-text-secondary hover:border-text-secondary/20"
            }`}
          >
            <Calendar size={12} className="inline mr-1.5" />
            Last {range === "7d" ? "7 Days" : range === "30d" ? "30 Days" : "90 Days"}
          </button>
        ))}
      </div>

      {/* Trends Chart */}
      <div className="border border-structural bg-surface/20 p-5 mb-6">
        <div className="flex items-center gap-2 mb-4">
          <TrendingUp size={14} className="text-prism-cyan" />
          <h2 className="text-sm font-medium text-text-primary tracking-wide uppercase">Vulnerability Discovery Trends</h2>
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
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-structural)" />
            <XAxis dataKey="date" tick={{ fill: "var(--text-secondary)", fontSize: 10, fontFamily: "monospace" }} axisLine={{ stroke: "var(--border-structural)" }} />
            <YAxis tick={{ fill: "var(--text-secondary)", fontSize: 10, fontFamily: "monospace" }} axisLine={{ stroke: "var(--border-structural)" }} />
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--bg-surface)",
                border: "1px solid var(--border-structural)",
                color: "var(--text-primary)",
                fontSize: 11,
              }}
            />
            <Area type="monotone" dataKey="critical" stroke="#FF4444" fillOpacity={1} fill="url(#colorCritical)" />
            <Area type="monotone" dataKey="high" stroke="#FF8800" fillOpacity={1} fill="url(#colorHigh)" />
            <Area type="monotone" dataKey="medium" stroke="var(--prism-cream)" fill="var(--prism-cream)" fillOpacity={0.1} />
            <Area type="monotone" dataKey="low" stroke="var(--prism-cyan)" fill="var(--prism-cyan)" fillOpacity={0.1} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="grid grid-cols-2 gap-6 mb-6">
        {/* Severity Distribution */}
        <div className="border border-structural bg-surface/20 p-5">
          <div className="flex items-center gap-2 mb-4">
            <ShieldAlert size={14} className="text-prism-cream" />
            <h2 className="text-sm font-medium text-text-primary tracking-wide uppercase">Severity Distribution</h2>
          </div>
          <div className="flex items-center gap-6">
            <ResponsiveContainer width={180} height={180}>
              <PieChart>
                <Pie data={severityDistribution} cx="50%" cy="50%" innerRadius={45} outerRadius={75} paddingAngle={3} dataKey="value" stroke="none">
                  {severityDistribution.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: "var(--bg-surface)",
                    border: "1px solid var(--border-structural)",
                    color: "var(--text-primary)",
                    fontSize: 11,
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="space-y-2">
              {severityDistribution.map((entry, index) => (
                <div key={entry.name} className="flex items-center gap-2">
                  <div className="w-2 h-2" style={{ backgroundColor: PIE_COLORS[index % PIE_COLORS.length] }} />
                  <span className="text-[10px] font-mono text-text-secondary">{entry.name}: {entry.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Engagement Comparison */}
        <div className="border border-structural bg-surface/20 p-5">
          <div className="flex items-center gap-2 mb-4">
            <Activity size={14} className="text-prism-cyan" />
            <h2 className="text-sm font-medium text-text-primary tracking-wide uppercase">Engagement Comparison</h2>
          </div>
          <div className="space-y-2 max-h-[200px] overflow-y-auto">
            {comparisons.length === 0 ? (
              <p className="text-[10px] font-mono text-text-secondary/40 uppercase tracking-widest text-center py-8">No engagement data</p>
            ) : (
              comparisons.map((eng) => (
                <div key={eng.id} className="flex items-center justify-between px-3 py-2 border border-structural bg-surface/10 hover:bg-surface/20 transition-colors">
                  <div className="min-w-0">
                    <div className="text-[11px] text-text-primary font-mono truncate">{eng.target_url}</div>
                    <div className="text-[9px] text-text-secondary">{Math.round(eng.duration_minutes)}m</div>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <span className="text-[9px] font-mono text-red-400">{eng.critical_count}C</span>
                    <span className="text-[9px] font-mono text-orange-400">{eng.high_count}H</span>
                    <span className="text-[9px] font-mono text-prism-cream">{eng.findings_count} total</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Scheduled Reports */}
      <div className="border border-structural bg-surface/20 p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Mail size={14} className="text-prism-cream" />
            <h2 className="text-sm font-medium text-text-primary tracking-wide uppercase">Scheduled Reports</h2>
          </div>
          <button
            onClick={() => setShowScheduleForm(!showScheduleForm)}
            className="flex items-center gap-2 px-4 py-2 bg-prism-cream text-void text-[10px] font-bold uppercase tracking-widest hover:opacity-90 transition-all shadow-glow-cream"
          >
            {showScheduleForm ? <XCircle size={12} /> : <Plus size={12} />}
            {showScheduleForm ? "Cancel" : "New Schedule"}
          </button>
        </div>

        {showScheduleForm && (
          <div className="border border-structural bg-surface/30 p-4 mb-4 space-y-3">
            <div>
              <label className="block text-[10px] font-bold text-text-secondary uppercase tracking-wider mb-1">Report Name</label>
              <input
                type="text"
                value={newReport.name}
                onChange={(e) => setNewReport((p) => ({ ...p, name: e.target.value }))}
                placeholder="Weekly Security Summary"
                className="w-full px-3 py-2 bg-surface/50 border border-structural text-xs text-text-primary outline-none focus:border-prism-cream transition-colors font-mono"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[10px] font-bold text-text-secondary uppercase tracking-wider mb-1">Frequency</label>
                <select
                  value={newReport.frequency}
                  onChange={(e) => setNewReport((p) => ({ ...p, frequency: e.target.value }))}
                  className="w-full px-3 py-2 bg-surface/50 border border-structural text-xs text-text-primary outline-none focus:border-prism-cream transition-colors font-mono"
                >
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                  <option value="quarterly">Quarterly</option>
                </select>
              </div>
              <div>
                <label className="block text-[10px] font-bold text-text-secondary uppercase tracking-wider mb-1">Report Type</label>
                <select
                  value={newReport.report_type}
                  onChange={(e) => setNewReport((p) => ({ ...p, report_type: e.target.value }))}
                  className="w-full px-3 py-2 bg-surface/50 border border-structural text-xs text-text-primary outline-none focus:border-prism-cream transition-colors font-mono"
                >
                  <option value="summary">Summary</option>
                  <option value="executive">Executive</option>
                  <option value="detailed">Detailed</option>
                  <option value="comparative">Comparative</option>
                </select>
              </div>
            </div>
            <div>
              <label className="block text-[10px] font-bold text-text-secondary uppercase tracking-wider mb-1">Email Recipients (comma-separated)</label>
              <input
                type="text"
                value={newReport.recipients}
                onChange={(e) => setNewReport((p) => ({ ...p, recipients: e.target.value }))}
                placeholder="security@company.com, ciso@company.com"
                className="w-full px-3 py-2 bg-surface/50 border border-structural text-xs text-text-primary outline-none focus:border-prism-cream transition-colors font-mono"
              />
            </div>
            <button
              onClick={handleCreateScheduledReport}
              className="px-5 py-2 bg-prism-cream text-void text-[10px] font-bold uppercase tracking-widest hover:opacity-90 transition-all shadow-glow-cream"
            >
              Create Scheduled Report
            </button>
          </div>
        )}

        <div className="space-y-2">
          {scheduledReports.length === 0 ? (
            <p className="text-[10px] font-mono text-text-secondary/40 uppercase tracking-widest text-center py-8">No scheduled reports</p>
          ) : (
            scheduledReports.map((report) => (
              <div key={report.id} className="flex items-center justify-between px-4 py-3 border border-structural bg-surface/10 hover:bg-surface/20 transition-colors">
                <div className="flex items-center gap-3">
                  <div className={`w-2 h-2 ${report.is_active ? "bg-green-400" : "bg-text-secondary"}`} />
                  <div>
                    <div className="text-xs text-text-primary font-mono">{report.name}</div>
                    <div className="text-[9px] text-text-secondary uppercase">
                      {report.report_type} · {report.frequency} · {report.email_recipients?.length || 0} recipients
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {report.next_run_at && (
                    <span className="text-[9px] font-mono text-text-secondary">
                      <Clock size={10} className="inline mr-1" />
                      {new Date(report.next_run_at).toLocaleDateString()}
                    </span>
                  )}
                  <button
                    onClick={() => handleSendEmailReport(report.id)}
                    className="p-1.5 text-text-secondary hover:text-prism-cyan transition-colors"
                    title="Send now"
                  >
                    <Mail size={12} />
                  </button>
                  <button
                    onClick={() => handleDeleteScheduledReport(report.id)}
                    className="p-1.5 text-text-secondary hover:text-red-500 transition-colors"
                    title="Delete"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
