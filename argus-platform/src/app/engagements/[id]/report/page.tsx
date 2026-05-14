"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { motion } from "framer-motion";
import {
  FileBarChart,
  Download,
  Loader2,
  ArrowLeft,
  ShieldAlert,
  ShieldCheck,
  Shield,
  ShieldOff,
  Activity,
} from "lucide-react";

interface ReportData {
  id: string;
  engagement_id: string;
  executive_summary: string | null;
  full_report_json: Record<string, unknown> | null;
  risk_level: string | null;
  total_findings: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  model_used: string | null;
  created_at: string;
}

const riskConfig: Record<string, { color: string; icon: typeof ShieldAlert; label: string }> = {
  critical: { color: "#FF4444", icon: ShieldAlert, label: "Critical" },
  high: { color: "#FF8800", icon: ShieldAlert, label: "High" },
  medium: { color: "#FFB800", icon: Shield, label: "Medium" },
  low: { color: "#10B981", icon: ShieldCheck, label: "Low" },
  none: { color: "#7A7489", icon: ShieldOff, label: "None" },
};

export default function EngagementReportPage() {
  const params = useParams();
  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();
  const engagementId = params.id as string;

  const [report, setReport] = useState<ReportData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status === "unauthenticated") {
      signIn();
    }
  }, [status]);

  useEffect(() => {
    if (status !== "authenticated" || !engagementId) return;

    const fetchReport = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const response = await fetch(`/api/reports/${engagementId}`);
        if (response.ok) {
          const data = await response.json();
          setReport(data.report);
        } else if (response.status === 404) {
          setError("No report found for this engagement. The scan may have completed but report generation may not have run, or the engagement is still processing.");
        } else {
          setError("Failed to load report.");
        }
      } catch {
        setError("Failed to connect to the server.");
      } finally {
        setIsLoading(false);
      }
    };

    fetchReport();
  }, [status, engagementId]);

  const handleDownload = async () => {
    if (!report) return;
    try {
      const response = await fetch(`/api/reports/${report.id}/download`);
      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `report-${report.id}.pdf`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        showToast("success", "Report downloaded");
      } else {
        showToast("error", "Failed to download report");
      }
    } catch {
      showToast("error", "Download failed");
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

  const risk = riskConfig[report?.risk_level || "none"] || riskConfig.none;
  const RiskIcon = risk.icon;

  return (
    <div className="min-h-screen px-6 py-6 bg-background dark:bg-[#0A0A0F] font-body">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-6"
      >
        <button
          onClick={() => router.push(`/engagements/${engagementId}`)}
          className="flex items-center gap-2 text-sm text-on-surface-variant hover:text-on-surface transition-colors mb-3"
        >
          <ArrowLeft size={14} />
          Back to Engagement
        </button>

        <div className="flex items-center gap-2 mb-2">
          <FileBarChart size={18} className="text-primary" />
          <span className="text-[11px] font-mono text-on-surface-variant tracking-widest uppercase">
            Engagement Report
          </span>
        </div>
        <div className="flex items-center justify-between">
          <h1 className="text-3xl font-semibold text-on-surface dark:text-white tracking-tight font-headline">
            Scan Report
          </h1>
          {report && (
            <button
              onClick={handleDownload}
              className="flex items-center gap-2 px-5 py-2.5 bg-primary text-white font-bold text-xs tracking-widest uppercase hover:bg-primary/90 transition-all duration-300 rounded-lg shadow-glow"
            >
              <Download size={14} />
              Download PDF
            </button>
          )}
        </div>
      </motion.div>

      {/* Error State */}
      {error && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-8 text-center"
        >
          <FileBarChart size={48} className="text-on-surface-variant/30 mx-auto mb-4" />
          <p className="text-on-surface-variant text-sm mb-4">{error}</p>
          <button
            onClick={() => router.push(`/engagements/${engagementId}`)}
            className="px-4 py-2 border border-primary/30 text-primary text-xs font-bold uppercase tracking-widest rounded-lg hover:bg-primary/10 transition-all"
          >
            Back to Engagement
          </button>
        </motion.div>
      )}

      {/* Report Content */}
      {report && (
        <>
          {/* Risk Level Banner */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="mb-6 p-5 rounded-xl border flex items-center gap-4"
            style={{
              backgroundColor: `${risk.color}10`,
              borderColor: `${risk.color}30`,
            }}
          >
            <RiskIcon size={32} style={{ color: risk.color }} />
            <div>
              <div className="text-[10px] font-mono uppercase tracking-widest text-on-surface-variant mb-1">
                Overall Risk Level
              </div>
              <div className="text-2xl font-headline font-semibold" style={{ color: risk.color }}>
                {risk.label}
              </div>
            </div>
            {report.model_used && (
              <div className="ml-auto text-right">
                <div className="text-[10px] font-mono uppercase tracking-widest text-on-surface-variant">
                  Generated by
                </div>
                <div className="text-xs font-mono text-on-surface">{report.model_used}</div>
              </div>
            )}
          </motion.div>

          {/* Findings Summary Cards */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 }}
            className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6"
          >
            {[
              { label: "Total Findings", value: report.total_findings, color: "#6720FF" },
              { label: "Critical", value: report.critical_count, color: "#FF4444" },
              { label: "High", value: report.high_count, color: "#FF8800" },
              { label: "Medium", value: report.medium_count, color: "#FFB800" },
              { label: "Low", value: report.low_count, color: "#10B981" },
            ].map((stat) => (
              <div
                key={stat.label}
                className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-4"
              >
                <div className="text-[10px] font-mono uppercase tracking-widest text-on-surface-variant mb-2">
                  {stat.label}
                </div>
                <div className="text-3xl font-headline font-bold" style={{ color: stat.color }}>
                  {stat.value}
                </div>
              </div>
            ))}
          </motion.div>

          {/* Executive Summary */}
          {report.executive_summary && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-6 mb-6"
            >
              <div className="flex items-center gap-2 mb-4">
                <Activity size={16} className="text-primary" />
                <h2 className="text-sm font-headline font-semibold text-on-surface dark:text-white uppercase tracking-widest">
                  Executive Summary
                </h2>
              </div>
              <p className="text-sm text-on-surface-variant leading-relaxed whitespace-pre-wrap font-body">
                {report.executive_summary}
              </p>
            </motion.div>
          )}

          {/* Full Report JSON */}
          {report.full_report_json && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.25 }}
              className="bg-surface dark:bg-surface-container-low rounded-xl border border-outline-variant dark:border-outline/30 p-6"
            >
              <div className="flex items-center gap-2 mb-4">
                <FileBarChart size={16} className="text-primary" />
                <h2 className="text-sm font-headline font-semibold text-on-surface dark:text-white uppercase tracking-widest">
                  Full Report Data
                </h2>
              </div>
              <pre className="text-xs font-mono text-on-surface-variant bg-background dark:bg-[#0A0A0F] p-4 rounded-lg overflow-auto max-h-96 whitespace-pre-wrap">
                {JSON.stringify(report.full_report_json, null, 2)}
              </pre>
            </motion.div>
          )}

          {/* Metadata */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
            className="mt-6 flex items-center gap-6 text-[10px] font-mono text-on-surface-variant uppercase tracking-widest"
          >
            <span>Report ID: {report.id}</span>
            <span>Generated: {new Date(report.created_at).toLocaleString()}</span>
            {report.model_used && <span>Model: {report.model_used}</span>}
          </motion.div>
        </>
      )}
    </div>
  );
}
