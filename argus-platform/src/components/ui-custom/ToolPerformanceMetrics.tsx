"use client";

import { useMemo } from "react";
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
  PieChart,
  Pie,
  Cell,
} from "recharts";
import { Cpu, TrendingUp, Activity, Clock } from "lucide-react";

interface ToolMetric {
  tool_name: string;
  total_executions: number;
  success_count: number;
  avg_duration_ms: number;
  success_rate: number;
}

interface ToolPerformanceMetricsProps {
  metrics: ToolMetric[];
  days?: number;
}

const COLORS = ["var(--prism-cyan)", "var(--prism-cream)", "#FF8800", "#00FF88", "#FF4444", "#8A8A9E"];

function MetricCard({ label, value, icon: Icon, color }: { label: string; value: string | number; icon: React.ElementType; color: string }) {
  return (
    <div className="border border-structural bg-surface/30 p-4">
      <div className="flex items-center gap-2 mb-2">
        <Icon size={14} style={{ color }} />
        <span className="text-[10px] font-mono text-text-secondary uppercase tracking-wider">{label}</span>
      </div>
      <div className="text-xl font-semibold" style={{ color }}>{value}</div>
    </div>
  );
}

export default function ToolPerformanceMetrics({ metrics, days = 7 }: ToolPerformanceMetricsProps) {
  const chartData = useMemo(() => {
    return metrics.map((m) => ({
      name: m.tool_name,
      executions: parseInt(String(m.total_executions)) || 0,
      successRate: parseFloat(String(m.success_rate)) || 0,
      avgDuration: Math.round(parseFloat(String(m.avg_duration_ms)) || 0),
    }));
  }, [metrics]);

  const summary = useMemo(() => {
    const total = metrics.reduce((sum, m) => sum + (parseInt(String(m.total_executions)) || 0), 0);
    const avgSuccess = metrics.length > 0
      ? metrics.reduce((sum, m) => sum + (parseFloat(String(m.success_rate)) || 0), 0) / metrics.length
      : 0;
    const avgDuration = metrics.length > 0
      ? metrics.reduce((sum, m) => sum + (parseFloat(String(m.avg_duration_ms)) || 0), 0) / metrics.length
      : 0;
    return { total, avgSuccess, avgDuration };
  }, [metrics]);

  const pieData = useMemo(() => {
    return metrics.map((m) => ({
      name: m.tool_name,
      value: parseInt(String(m.total_executions)) || 0,
    }));
  }, [metrics]);

  if (metrics.length === 0) {
    return (
      <div className="w-full border border-structural bg-surface/20 p-8 text-center">
        <Cpu size={24} className="text-text-secondary/40 mx-auto mb-3" />
        <p className="text-[11px] font-mono text-text-secondary/40 uppercase tracking-widest">No tool metrics available</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-3">
        <MetricCard label="Total Executions" value={summary.total} icon={Activity} color="var(--prism-cyan)" />
        <MetricCard label="Avg Success Rate" value={`${summary.avgSuccess.toFixed(1)}%`} icon={TrendingUp} color="var(--prism-cream)" />
        <MetricCard label="Avg Duration" value={`${Math.round(summary.avgDuration)}ms`} icon={Clock} color="#00FF88" />
        <MetricCard label="Active Tools" value={metrics.length} icon={Cpu} color="#FF8800" />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-2 gap-4">
        {/* Executions Bar Chart */}
        <div className="border border-structural bg-surface/20 p-4">
          <div className="flex items-center gap-2 mb-3">
            <Activity size={14} className="text-prism-cyan" />
            <span className="text-[10px] font-bold uppercase tracking-widest text-text-secondary">Executions by Tool ({days}d)</span>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-structural)" />
              <XAxis dataKey="name" tick={{ fill: "var(--text-secondary)", fontSize: 10, fontFamily: "monospace" }} axisLine={{ stroke: "var(--border-structural)" }} />
              <YAxis tick={{ fill: "var(--text-secondary)", fontSize: 10, fontFamily: "monospace" }} axisLine={{ stroke: "var(--border-structural)" }} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "var(--bg-surface)",
                  border: "1px solid var(--border-structural)",
                  color: "var(--text-primary)",
                  fontSize: 11,
                }}
              />
              <Bar dataKey="executions" fill="var(--prism-cyan)" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Success Rate Line Chart */}
        <div className="border border-structural bg-surface/20 p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp size={14} className="text-prism-cream" />
            <span className="text-[10px] font-bold uppercase tracking-widest text-text-secondary">Success Rate by Tool (%)</span>
          </div>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-structural)" />
              <XAxis dataKey="name" tick={{ fill: "var(--text-secondary)", fontSize: 10, fontFamily: "monospace" }} axisLine={{ stroke: "var(--border-structural)" }} />
              <YAxis tick={{ fill: "var(--text-secondary)", fontSize: 10, fontFamily: "monospace" }} axisLine={{ stroke: "var(--border-structural)" }} domain={[0, 100]} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "var(--bg-surface)",
                  border: "1px solid var(--border-structural)",
                  color: "var(--text-primary)",
                  fontSize: 11,
                }}
              />
              <Line type="monotone" dataKey="successRate" stroke="var(--prism-cream)" strokeWidth={2} dot={{ fill: "var(--prism-cream)", r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Distribution Pie Chart */}
      <div className="border border-structural bg-surface/20 p-4">
        <div className="flex items-center gap-2 mb-3">
          <Cpu size={14} className="text-prism-cyan" />
          <span className="text-[10px] font-bold uppercase tracking-widest text-text-secondary">Execution Distribution</span>
        </div>
        <div className="flex items-center gap-8">
          <ResponsiveContainer width={200} height={160}>
            <PieChart>
              <Pie
                data={pieData}
                cx="50%"
                cy="50%"
                innerRadius={40}
                outerRadius={70}
                paddingAngle={2}
                dataKey="value"
                stroke="none"
              >
                {pieData.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
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
          <div className="flex flex-wrap gap-3">
            {pieData.map((entry, index) => (
              <div key={entry.name} className="flex items-center gap-1.5">
                <div className="w-2 h-2" style={{ backgroundColor: COLORS[index % COLORS.length] }} />
                <span className="text-[10px] font-mono text-text-secondary">{entry.name}: {entry.value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
