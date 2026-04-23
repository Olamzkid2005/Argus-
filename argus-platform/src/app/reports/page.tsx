"use client";

import { useState, useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { motion, AnimatePresence } from "framer-motion";
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
  ShieldCheck,
  Plus,
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
  engagement: { color: "#6720FF", label: "Engagement" },
  finding: { color: "#FF8800", label: "Finding" },
  summary: { color: "#7A7489", label: "Summary" },
  executive: { color: "#FF4444", label: "Executive" },
};

const statusConfig = {
  generating: { color: "#6720FF", label: "Generating", bg: "bg-primary/10" },
  ready: { color: "#10B981", label: "Ready", bg: "bg-green-500/10" },
  failed: { color: "#FF4444", label: "Failed", bg: "bg-error/10" },
};

// ── Main Page ──
export default function ReportsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
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
          setReports([]);
        }
      } catch (err) {
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
          <FileBarChart size={18} className="text-primary" />
          <span className="text-[11px] font-mono text-on-surface-variant tracking-widest uppercase">
            Intelligence Reports
          </span>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-semibold text-on-surface dark:text-white tracking-tight font-headline">Reports</h1>
            <p className="text-sm text-on-surface-variant mt-1 font-body">
              Generate and manage vulnerability assessment reports
            </p>
          </div>
          <div className="flex items-center gap-3">
            <ScannerReveal
              icon="/assets/holographic-lock.png"
              text="AUTO-SCHEDULE"
              scannedText="CONFIGURED"
              className="h-10 border-outline-variant dark:border-outline/30"
              glowColor="var(--primary)"
            />
          </div>
        </div>
      </motion.div>

      {/* Actions Bar */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="flex items-center justify-between mb-6"
      >
        <div className="flex items-center gap-3">
          <button
            onClick={handleGenerateReport}
            disabled={isGenerating}
            className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white font-bold text-xs tracking-widest uppercase hover:bg-primary/90 transition-all duration-300 rounded-lg shadow-glow disabled:opacity-50"
          >
            {isGenerating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
            {isGenerating ? "GENERATING..." : "Generate Report"}
          </button>

          <button
            onClick={() => router.push("/reports/compliance")}
            className="flex items-center gap-2 px-5 py-2.5 border border-primary/30 text-primary font-bold text-xs tracking-widest uppercase hover:bg-primary/10 transition-all duration-300 rounded-lg"
          >
            <ShieldCheck size={14} />
            Compliance
          </button>
        </div>
      </motion.div>

      {/* Type Filter Tabs */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
        className="flex items-center gap-2 mb-4 flex-wrap"
      >
        <button
          onClick={() => setTypeFilter("All")}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-[10px] font-bold uppercase tracking-widest transition-all duration-300 ${
            typeFilter === "All"
              ? "bg-primary text-white shadow-glow"
              : "bg-surface dark:bg-surface-container-low text-on-surface-variant border border-outline-variant dark:border-outline/30 hover:text-on-surface"
          }`}
        >
          All
          <span className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-white/20">
            {reports.length}
          </span>
        </button>
        {(["engagement", "finding", "summary", "executive"] as const).map((type) => (
          <button
            key={type}
            onClick={() => setTypeFilter(typeFilter === type ? "All" : type)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-[10px] font-bold uppercase tracking-widest transition-all duration-300 ${
              typeFilter === type
                ? "bg-primary text-white shadow-glow"
                : "bg-surface dark:bg-surface-container-low text-on-surface-variant border border-outline-variant dark:border-outline/30 hover:text-on-surface"
            }`}
          >
            {reportTypeConfig[type].label}
            <span
              className="text-[11px] font-mono px-1.5 py-0.5 rounded"
              style={{
                color: typeFilter === type ? "white" : reportTypeConfig[type].color,
                backgroundColor: typeFilter === type ? "rgba(255,255,255,0.2)" : "rgba(0,0,0,0.05)",
              }}
            >
              {reportCounts[type] || 0}
            </span>
          </button>
        ))}
      </motion.div>

      {/* Search Bar */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="flex items-center gap-3 mb-4"
      >
        <div className="flex-1 flex items-center gap-2 px-4 py-2.5 bg-surface dark:bg-surface-container-low border border-outline-variant dark:border-outline/30 rounded-lg transition-all duration-300 focus-within:border-primary focus-within:shadow-glow">
          <Search size={14} className="text-on-surface-variant shrink-0" />
          <input
            type="text"
            placeholder="Search reports by name, ID, or engagement..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="flex-1 bg-transparent text-sm text-on-surface outline-none placeholder:text-on-surface-variant/60 font-body"
          />
        </div>
        <button className="flex items-center gap-2 px-4 py-2.5 bg-surface dark:bg-surface-container-low border border-outline-variant dark:border-outline/30 text-on-surface-variant hover:text-on-surface transition-all duration-300 rounded-lg text-xs uppercase font-bold tracking-widest">
          <Filter size={14} />
          Filter
        </button>
      </motion.div>

      {/* Reports Table */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.25 }}
        className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 overflow-hidden"
      >
        {/* Table Header */}
        <div className="grid grid-cols-[80px_1fr_100px_100px_80px_100px_100px] gap-4 px-5 py-3 border-b border-outline-variant dark:border-outline/30 text-[11px] font-mono text-on-surface-variant tracking-wider uppercase bg-surface-container-low/50 dark:bg-surface-container/50">
          <span>ID</span>
          <span>Report Name</span>
          <span>Type</span>
          <span>Status</span>
          <span>Format</span>
          <span>Created</span>
          <span className="text-right">Actions</span>
        </div>

        {/* Table Body */}
        <AnimatePresence>
          {filtered.map((report, index) => {
            const typeStyle = reportTypeConfig[report.type];
            const statusStyle = statusConfig[report.status];
            const isReady = report.status === "ready";

            return (
              <motion.div
                key={report.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ delay: index * 0.02 }}
                className="grid grid-cols-[80px_1fr_100px_100px_80px_100px_100px] gap-4 px-5 py-3.5 items-center border-b border-outline-variant dark:border-outline/30 last:border-b-0 hover:bg-surface-container-low/50 dark:hover:bg-surface-container/50 transition-all duration-300"
              >
                <span className="text-[11px] font-mono text-on-surface-variant uppercase">
                  {report.id.split("-")[0]}
                </span>

                <div className="flex items-center gap-3 min-w-0">
                  <FileBarChart size={16} style={{ color: typeStyle.color }} />
                  <div className="min-w-0">
                    <div className="text-sm text-on-surface truncate font-body">{report.name}</div>
                    {report.engagement_id && (
                      <div className="text-[10px] text-on-surface-variant font-mono mt-0.5">
                        Engagement: {report.engagement_id}
                      </div>
                    )}
                  </div>
                </div>

                <span
                  className="text-[10px] font-mono font-bold px-2 py-0.5 rounded border w-fit"
                  style={{
                    color: typeStyle.color,
                    borderColor: `${typeStyle.color}30`,
                    backgroundColor: `${typeStyle.color}10`,
                  }}
                >
                  {typeStyle.label}
                </span>

                <div className="flex items-center gap-2">
                  <div
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ backgroundColor: statusStyle.color }}
                  />
                  <span className="text-[11px] text-on-surface-variant uppercase">{statusStyle.label}</span>
                </div>

                <span className="text-[11px] font-mono text-on-surface-variant uppercase">
                  {report.format.toUpperCase()}
                </span>

                <span className="text-[11px] font-mono text-on-surface-variant">
                  {new Date(report.created_at).toLocaleDateString()}
                </span>

                <div className="flex items-center justify-end gap-1">
                  {isReady && (
                    <>
                      <button
                        onClick={() => handleDownload(report.id)}
                        className="p-1.5 text-on-surface-variant hover:text-primary transition-all duration-300 rounded"
                        title="Download"
                      >
                        <Download size={14} />
                      </button>
                      <button
                        className="p-1.5 text-on-surface-variant hover:text-primary transition-all duration-300 rounded"
                        title="Share"
                      >
                        <Share2 size={14} />
                      </button>
                    </>
                  )}
                  <button
                    onClick={() => handleDelete(report.id)}
                    className="p-1.5 text-on-surface-variant hover:text-error transition-all duration-300 rounded"
                    title="Delete"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>

        {filtered.length === 0 && (
          <div className="px-5 py-20 text-center text-on-surface-variant/40 italic text-sm tracking-widest uppercase">
            NO REPORTS FOUND IN SELECTED TELEMETRY
          </div>
        )}
      </motion.div>
    </div>
  );
}
