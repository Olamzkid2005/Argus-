"use client";

import { useState, useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import {
  FileBarChart,
  FileText,
  Download,
  Calendar,
  Filter,
  Search,
  ChevronRight,
  Loader2,
  RefreshCcw,
  Eye,
  Trash2,
  Share2,
  Printer,
} from "lucide-react";
import ScannerReveal from "@/components/effects/ScannerReveal";

// ── Types ──
interface Report {
  id: string;
  name: string;
  type: "engagement" | "finding" | "summary" | "executive";
  engagement_id?: string;
  status: "generating" | "ready" | "failed";
  created_at: string;
  file_size?: number;
  format: "pdf" | "html" | "json";
}

// ── Helpers ──
const reportTypeConfig = {
  engagement: { color: "var(--prism-cyan)", label: "Engagement" },
  finding: { color: "var(--prism-cream)", label: "Finding" },
  summary: { color: "var(--text-secondary)", label: "Summary" },
  executive: { color: "#FF8800", label: "Executive" },
};

const statusConfig = {
  generating: { color: "var(--prism-cyan)", label: "Generating" },
  ready: { color: "#00FF88", label: "Ready" },
  failed: { color: "#FF4444", label: "Failed" },
};

// ── Main Page ──
export default function ReportsPage() {
  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();

  const [reports, setReports] = useState<Report[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("All");
  const [isGenerating, setIsGenerating] = useState(false);

  useEffect(() => {
    if (status === "unauthenticated") {
      signIn();
    }
  }, [status, router]);

  useEffect(() => {
    if (status !== "authenticated") return;

    const fetchReports = async () => {
      setIsLoading(true);
      try {
        const response = await fetch("/api/reports");
        if (response.ok) {
          const data = await response.json();
          setReports(data.reports || []);
        } else {
          // If API doesn't exist, use empty array for demo
          setReports([]);
        }
      } catch (err) {
        // Silently fail - demo mode
        setReports([]);
      } finally {
        setIsLoading(false);
      }
    };

    fetchReports();
  }, [status]);

  const handleGenerateReport = async () => {
    setIsGenerating(true);
    try {
      const response = await fetch("/api/reports/generate", { method: "POST" });
      if (response.ok) {
        const data = await response.json();
        showToast("success", "Report generation started");
        // Refresh reports list
        const reportsResponse = await fetch("/api/reports");
        if (reportsResponse.ok) {
          const data = await reportsResponse.json();
          setReports(data.reports || []);
        }
      } else {
        showToast("error", "Failed to initiate report generation");
      }
    } catch (err) {
      showToast("error", "Failed to generate report");
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDownload = async (reportId: string) => {
    try {
      const response = await fetch(`/api/reports/${reportId}/download`);
      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `report-${reportId}.pdf`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        showToast("success", "Report downloaded");
      } else {
        showToast("error", "Failed to download report");
      }
    } catch (err) {
      showToast("error", "Download failed");
    }
  };

  const handleDelete = async (reportId: string) => {
    if (!confirm("Are you sure you want to delete this report?")) return;
    try {
      const response = await fetch(`/api/reports/${reportId}`, { method: "DELETE" });
      if (response.ok) {
        showToast("success", "Report deleted");
        setReports((prev) => prev.filter((r) => r.id !== reportId));
      }
    } catch (err) {
      showToast("error", "Failed to delete report");
    }
  };

  const filtered = useMemo(() => {
    return reports.filter((r) => {
      const matchesSearch =
        r.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        r.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (r.engagement_id && r.engagement_id.toLowerCase().includes(searchQuery.toLowerCase()));
      const matchesType = typeFilter === "All" || r.type === typeFilter;
      return matchesSearch && matchesType;
    });
  }, [reports, searchQuery, typeFilter]);

  const reportCounts = useMemo(() => {
    return reports.reduce(
      (acc, r) => {
        acc[r.type] = (acc[r.type] || 0) + 1;
        return acc;
      },
      {} as Record<string, number>
    );
  }, [reports]);

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
          <FileBarChart size={18} className="text-prism-cream" />
          <span className="text-[11px] font-mono text-text-secondary tracking-widest uppercase">
            Intelligence Reports
          </span>
        </div>
        <h1 className="text-4xl font-semibold text-text-primary tracking-tight">REPORTS</h1>
        <p className="text-sm text-text-secondary mt-2">
          Generate and manage vulnerability assessment reports
        </p>
      </div>

      {/* Actions Bar */}
      <div className="flex items-center justify-between mb-6">
        <button
          onClick={handleGenerateReport}
          disabled={isGenerating}
          className="flex items-center gap-2 px-6 py-2.5 bg-prism-cream text-void font-bold text-xs tracking-widest uppercase hover:opacity-90 transition-all shadow-glow-cream disabled:opacity-50"
        >
          {isGenerating ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <FileText size={14} />
          )}
          {isGenerating ? "GENERATING..." : "GENERATE REPORT"}
        </button>

        <div className="flex items-center gap-3">
          <ScannerReveal
            icon="/assets/holographic-lock.png"
            text="AUTO-SCHEDULE"
            scannedText="CONFIGURED"
            className="h-10 border-structural"
            glowColor="var(--prism-cyan)"
          />
        </div>
      </div>

      {/* Type Filter Bar */}
      <div className="flex gap-3 mb-6">
        <button
          onClick={() => setTypeFilter("All")}
          className={`flex items-center gap-2 px-4 py-2 border transition-all duration-200 ${
            typeFilter === "All"
              ? "border-prism-cream/40 bg-surface/50"
              : "border-structural bg-surface/30 hover:border-text-secondary/20"
          }`}
        >
          <span className="text-[10px] text-text-primary font-bold uppercase">All</span>
          <span className="text-[11px] font-mono px-1.5 py-0.5" style={{ backgroundColor: "var(--structural)", color: "var(--text-secondary)" }}>
            {reports.length}
          </span>
        </button>
        {(["engagement", "finding", "summary", "executive"] as const).map((type) => (
          <button
            key={type}
            onClick={() => setTypeFilter(typeFilter === type ? "All" : type)}
            className={`flex items-center gap-2 px-4 py-2 border transition-all duration-200 ${
              typeFilter === type
                ? "border-prism-cream/40 bg-surface/50"
                : "border-structural bg-surface/30 hover:border-text-secondary/20"
            }`}
          >
            <span className="text-[10px] text-text-primary font-bold uppercase">{reportTypeConfig[type].label}</span>
            <span
              className="text-[11px] font-mono px-1.5 py-0.5"
              style={{
                color: reportTypeConfig[type].color,
                backgroundColor: "var(--structural)",
              }}
            >
              {reportCounts[type] || 0}
            </span>
          </button>
        ))}
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3 mb-4">
        <div className="flex-1 flex items-center gap-2 px-3 py-2 border border-structural bg-surface/30 transition-all">
          <Search size={14} className="text-text-secondary shrink-0" />
          <input
            type="text"
            placeholder="Search reports by name, ID, or engagement..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="flex-1 bg-transparent text-sm text-text-primary outline-none placeholder:text-text-secondary/60"
          />
        </div>
        <button className="flex items-center gap-2 px-4 py-2 border border-structural text-text-secondary hover:text-text-primary hover:border-text-secondary/40 transition-all text-sm uppercase font-bold tracking-widest text-[10px]">
          <Filter size={14} />
          Filter
        </button>
      </div>

      {/* Reports Table */}
      <div className="border border-structural bg-surface/20">
        <div className="grid grid-cols-[100px_1fr_120px_120px_100px_100px_40px] gap-4 px-5 py-3 border-b border-structural text-[11px] font-mono text-text-secondary tracking-wider uppercase">
          <span>Report ID</span>
          <span>Report Name</span>
          <span>Type</span>
          <span>Status</span>
          <span>Format</span>
          <span>Created</span>
          <span></span>
        </div>

        {filtered.map((report) => {
          const typeStyle = reportTypeConfig[report.type];
          const statusStyle = statusConfig[report.status];
          const isReady = report.status === "ready";

          return (
            <div
              key={report.id}
              className="grid grid-cols-[100px_1fr_120px_120px_100px_100px_40px] gap-4 px-5 py-4 items-center border-b border-structural last:border-b-0 hover:bg-surface/10 transition-colors"
            >
              <span className="text-[11px] font-mono text-text-secondary uppercase">
                {report.id.split("-")[0]}
              </span>

              <div className="flex items-center gap-3">
                <FileBarChart size={16} style={{ color: typeStyle.color }} />
                <div>
                  <div className="text-sm text-text-primary">{report.name}</div>
                  {report.engagement_id && (
                    <div className="text-[10px] text-text-secondary font-mono mt-0.5">
                      Engagement: {report.engagement_id}
                    </div>
                  )}
                </div>
              </div>

              <span
                className="text-[10px] font-mono font-bold px-2 py-0.5 border w-fit"
                style={{
                  color: typeStyle.color,
                  borderColor: "var(--border-structural)",
                  backgroundColor: "transparent",
                }}
              >
                {typeStyle.label}
              </span>

              <div className="flex items-center gap-2">
                <div
                  className="w-1.5 h-1.5 rounded-full"
                  style={{ backgroundColor: statusStyle.color }}
                />
                <span className="text-[11px] text-text-secondary uppercase">
                  {statusStyle.label}
                </span>
              </div>

              <span className="text-[11px] font-mono text-text-secondary uppercase">
                {report.format.toUpperCase()}
              </span>

              <span className="text-[11px] font-mono text-text-secondary">
                {new Date(report.created_at).toLocaleDateString()}
              </span>

              <div className="flex items-center gap-2">
                {isReady && (
                  <>
                    <button
                      onClick={() => handleDownload(report.id)}
                      className="p-1.5 text-text-secondary hover:text-prism-cyan transition-colors"
                      title="Download"
                    >
                      <Download size={14} />
                    </button>
                    <button
                      className="p-1.5 text-text-secondary hover:text-prism-cream transition-colors"
                      title="Share"
                    >
                      <Share2 size={14} />
                    </button>
                  </>
                )}
                <button
                  onClick={() => handleDelete(report.id)}
                  className="p-1.5 text-text-secondary hover:text-red-500 transition-colors"
                  title="Delete"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          );
        })}

        {filtered.length === 0 && (
          <div className="px-5 py-20 text-center text-text-secondary/40 italic text-sm tracking-widest uppercase">
            NO REPORTS FOUND IN SELECTED TELEMETRY
          </div>
        )}
      </div>
    </div>
  );
}
