"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { log } from "@/lib/logger";
import {
  ShieldCheck,
  FileText,
  Loader2,
  ArrowLeft,
  Download,
  Eye,
  AlertTriangle,
  CheckCircle2,
  Clock,
} from "lucide-react";

interface ComplianceReport {
  id: string;
  engagement_id: string;
  standard: "owasp_top10" | "pci_dss" | "soc2";
  title: string;
  status: "generating" | "ready" | "failed";
  created_at: string;
  updated_at: string;
}

const standardConfig = {
  owasp_top10: {
    label: "OWASP Top 10",
    color: "#FF8800",
    description: "Web application security compliance",
  },
  pci_dss: {
    label: "PCI DSS 4.0",
    color: "#00FF88",
    description: "Payment card industry standards",
  },
  soc2: {
    label: "SOC 2",
    color: "#E9FFFF",
    description: "Trust services criteria",
  },
};

const statusConfig = {
  generating: { color: "var(--prism-cyan)", label: "Generating", icon: Clock },
  ready: { color: "#00FF88", label: "Ready", icon: CheckCircle2 },
  failed: { color: "#FF4444", label: "Failed", icon: AlertTriangle },
};

export default function ComplianceReportsPage() {
  useEffect(() => {
    log.pageMount("ComplianceReports");
    return () => log.pageUnmount("ComplianceReports");
  }, []);

  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();

  const [reports, setReports] = useState<ComplianceReport[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [selectedStandard, setSelectedStandard] = useState<string>("owasp_top10");
  const [engagementId, setEngagementId] = useState<string>("");
  const [engagements, setEngagements] = useState<{ id: string; target_url: string }[]>([]);

  useEffect(() => {
    if (status === "unauthenticated") {
      signIn();
    }
  }, [status, router]);

  useEffect(() => {
    if (status !== "authenticated") return;

    const fetchEngagements = async () => {
      try {
        const response = await fetch("/api/engagements?limit=50");
        if (response.ok) {
          const data = await response.json();
          setEngagements(data.engagements || []);
          if (data.engagements?.length > 0) {
            setEngagementId(data.engagements[0].id);
          }
        }
      } catch (err) {
        console.error("Failed to fetch engagements:", err);
      }
    };

    fetchEngagements();
  }, [status]);

  useEffect(() => {
    if (status !== "authenticated") return;

    const fetchReports = async () => {
      setIsLoading(true);
      try {
        const response = await fetch("/api/reports/compliance");
        if (response.ok) {
          const data = await response.json();
          setReports(data.reports || []);
        }
      } catch (err) {
        showToast("error", "Failed to load compliance reports");
      } finally {
        setIsLoading(false);
      }
    };

    fetchReports();
  }, [status, showToast]);

  const handleGenerate = async () => {
    if (!engagementId) {
      showToast("error", "Please select an engagement");
      return;
    }

    setIsGenerating(true);
    try {
      const response = await fetch("/api/reports/compliance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          engagement_id: engagementId,
          standard: selectedStandard,
        }),
      });

      if (response.ok) {
        showToast("success", "Compliance report generation started");
        // Refresh reports
        const reportsResponse = await fetch("/api/reports/compliance");
        if (reportsResponse.ok) {
          const data = await reportsResponse.json();
          setReports(data.reports || []);
        }
      } else {
        const data = await response.json();
        showToast("error", data.error || "Failed to generate report");
      }
    } catch (err) {
      showToast("error", "Failed to generate compliance report");
    } finally {
      setIsGenerating(false);
    }
  };

  const handleView = (reportId: string) => {
    router.push(`/reports/compliance/${reportId}`);
  };

  const handleDownload = async (reportId: string) => {
    try {
      const response = await fetch(`/api/reports/compliance/${reportId}`);
      if (response.ok) {
        const data = await response.json();
        const htmlContent = data.report?.html_content;
        if (htmlContent) {
          const blob = new Blob([htmlContent], { type: "text/html" });
          const url = window.URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `compliance-report-${reportId}.html`;
          document.body.appendChild(a);
          a.click();
          window.URL.revokeObjectURL(url);
          showToast("success", "Report downloaded");
        } else {
          showToast("error", "Report HTML not available yet");
        }
      }
    } catch (err) {
      showToast("error", "Failed to download report");
    }
  };

  if (status === "loading" || isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface">
        <Loader2 className="h-8 w-8 animate-spin text-on-surface" />
      </div>
    );
  }

  if (!session) return null;

  return (
    <div className="min-h-screen px-8 py-8 bg-surface">
      {/* Header */}
      <div className="mb-8">
        <button
          onClick={() => router.push("/reports")}
          className="flex items-center gap-2 text-on-surface-variant hover:text-on-surface transition-colors mb-4 text-sm"
        >
          <ArrowLeft size={14} />
          Back to Reports
        </button>
        <div className="flex items-center gap-2 mb-2">
          <ShieldCheck size={18} className="text-on-surface" />
          <span className="text-[11px] font-mono text-on-surface-variant tracking-widest uppercase">
            Compliance Framework
          </span>
        </div>
        <h1 className="text-4xl font-semibold text-on-surface tracking-tight">COMPLIANCE REPORTS</h1>
        <p className="text-sm text-on-surface-variant mt-2">
          Generate OWASP Top 10, PCI DSS, and SOC 2 compliance reports
        </p>
      </div>

      {/* Generate Report Panel */}
      <div className="border border-outline-variant bg-surface/20 p-6 mb-8">
        <h2 className="text-sm font-bold text-on-surface uppercase tracking-widest mb-4 flex items-center gap-2">
          <FileText size={14} className="text-on-surface" />
          Generate New Report
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <div>
            <label className="block text-[10px] font-mono text-on-surface-variant uppercase tracking-wider mb-2">
              Engagement
            </label>
            <select
              value={engagementId}
              onChange={(e) => setEngagementId(e.target.value)}
              className="w-full px-3 py-2 border border-outline-variant bg-surface/30 text-sm text-on-surface outline-none focus:border-prism-cream transition-colors font-mono text-xs"
            >
              <option value="" className="bg-surface">Select engagement...</option>
              {engagements.map((eng) => (
                <option key={eng.id} value={eng.id} className="bg-surface">
                  {eng.target_url}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-[10px] font-mono text-on-surface-variant uppercase tracking-wider mb-2">
              Compliance Standard
            </label>
            <select
              value={selectedStandard}
              onChange={(e) => setSelectedStandard(e.target.value)}
              className="w-full px-3 py-2 border border-outline-variant bg-surface/30 text-sm text-on-surface outline-none focus:border-prism-cream transition-colors font-mono text-xs"
            >
              <option value="owasp_top10" className="bg-surface">OWASP Top 10</option>
              <option value="pci_dss" className="bg-surface">PCI DSS 4.0</option>
              <option value="soc2" className="bg-surface">SOC 2 Type II</option>
            </select>
          </div>

          <div className="flex items-end">
            <button
              onClick={handleGenerate}
              disabled={isGenerating || !engagementId}
              className="flex items-center gap-2 px-6 py-2.5 bg-prism-cream text-void font-bold text-xs tracking-widest uppercase hover:opacity-90 transition-all shadow-glow disabled:opacity-50 w-full justify-center"
            >
              {isGenerating ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <ShieldCheck size={14} />
              )}
              {isGenerating ? "GENERATING..." : "GENERATE REPORT"}
            </button>
          </div>
        </div>

        <div className="text-[11px] text-on-surface-variant">
          {standardConfig[selectedStandard as keyof typeof standardConfig]?.description}
        </div>
      </div>

      {/* Reports List */}
      <div className="border border-outline-variant bg-surface/20">
        <div className="grid grid-cols-[100px_1fr_140px_120px_120px_100px] gap-4 px-5 py-3 border-b border-outline-variant text-[11px] font-mono text-on-surface-variant tracking-wider uppercase">
          <span>Report ID</span>
          <span>Title</span>
          <span>Standard</span>
          <span>Status</span>
          <span>Created</span>
          <span></span>
        </div>

        {reports.map((report) => {
          const standardStyle = standardConfig[report.standard];
          const statusStyle = statusConfig[report.status];
          const StatusIcon = statusStyle.icon;

          return (
            <div
              key={report.id}
              className="grid grid-cols-[100px_1fr_140px_120px_120px_100px] gap-4 px-5 py-4 items-center border-b border-outline-variant last:border-b-0 hover:bg-surface/10 transition-colors"
            >
              <span className="text-[11px] font-mono text-on-surface-variant uppercase">
                {report.id.split("-")[0]}
              </span>

              <div>
                <div className="text-sm text-on-surface">{report.title}</div>
                <div className="text-[10px] text-on-surface-variant font-mono mt-0.5">
                  Engagement: {report.engagement_id}
                </div>
              </div>

              <span
                className="text-[10px] font-mono font-bold px-2 py-0.5 border w-fit"
                style={{
                  color: standardStyle.color,
                  borderColor: "var(--border-outline-variant)",
                  backgroundColor: "transparent",
                }}
              >
                {standardStyle.label}
              </span>

              <div className="flex items-center gap-2">
                <StatusIcon size={14} style={{ color: statusStyle.color }} />
                <span className="text-[11px] text-on-surface-variant uppercase">
                  {statusStyle.label}
                </span>
              </div>

              <span className="text-[11px] font-mono text-on-surface-variant">
                {new Date(report.created_at).toLocaleDateString()}
              </span>

              <div className="flex items-center gap-2">
                {report.status === "ready" && (
                  <>
                    <button
                      onClick={() => handleView(report.id)}
                      className="p-1.5 text-on-surface-variant hover:text-prism-cyan transition-colors"
                      title="View"
                    >
                      <Eye size={14} />
                    </button>
                    <button
                      onClick={() => handleDownload(report.id)}
                      className="p-1.5 text-on-surface-variant hover:text-on-surface transition-colors"
                      title="Download"
                    >
                      <Download size={14} />
                    </button>
                  </>
                )}
              </div>
            </div>
          );
        })}

        {reports.length === 0 && (
          <div className="px-5 py-20 text-center text-on-surface-variant/40 italic text-sm tracking-widest uppercase">
            NO COMPLIANCE REPORTS GENERATED
          </div>
        )}
      </div>
    </div>
  );
}
