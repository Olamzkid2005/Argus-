"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { log } from "@/lib/logger";
import {
  ArrowLeft,
  Loader2,
  Download,
  ShieldCheck,
  AlertTriangle,
} from "lucide-react";

interface ComplianceReportDetail {
  id: string;
  engagement_id: string;
  standard: string;
  title: string;
  report_data: Record<string, unknown>;
  html_content: string | null;
  status: string;
  created_at: string;
}

export default function ComplianceReportViewPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  useEffect(() => {
    log.pageMount("ComplianceReportView");
    return () => log.pageUnmount("ComplianceReportView");
  }, []);

  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();

  const [report, setReport] = useState<ComplianceReportDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [reportId, setReportId] = useState<string>("");

  useEffect(() => {
    params.then((p) => setReportId(p.id));
  }, [params]);

  useEffect(() => {
    if (status === "unauthenticated") {
      signIn();
    }
  }, [status, router]);

  useEffect(() => {
    if (status !== "authenticated" || !reportId) return;

    const fetchReport = async () => {
      setIsLoading(true);
      try {
        const response = await fetch(`/api/reports/compliance/${reportId}`);
        if (response.ok) {
          const data = await response.json();
          setReport(data.report);
        } else {
          showToast("error", "Report not found");
        }
      } catch (err) {
        showToast("error", "Failed to load report");
      } finally {
        setIsLoading(false);
      }
    };

    fetchReport();
  }, [status, reportId, showToast]);

  const handleDownload = () => {
    if (!report?.html_content) return;
    const blob = new Blob([report.html_content], { type: "text/html" });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `compliance-report-${reportId}.html`;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(url);
  };

  if (status === "loading" || isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface">
        <Loader2 className="h-8 w-8 animate-spin text-on-surface" />
      </div>
    );
  }

  if (!session) return null;

  if (!report) {
    return (
      <div className="min-h-screen px-8 py-8 bg-surface">
        <button
          onClick={() => router.push("/reports/compliance")}
          className="flex items-center gap-2 text-on-surface-variant hover:text-on-surface transition-colors mb-4 text-sm"
        >
          <ArrowLeft size={14} />
          Back to Compliance Reports
        </button>
        <div className="text-on-surface-variant">Report not found</div>
      </div>
    );
  }

  const standardLabels: Record<string, string> = {
    owasp_top10: "OWASP Top 10",
    pci_dss: "PCI DSS 4.0",
    soc2: "SOC 2 Type II",
  };

  return (
    <div className="min-h-screen px-8 py-8 bg-surface">
      {/* Header */}
      <div className="mb-6">
        <button
          onClick={() => router.push("/reports/compliance")}
          className="flex items-center gap-2 text-on-surface-variant hover:text-on-surface transition-colors mb-4 text-sm"
        >
          <ArrowLeft size={14} />
          Back to Compliance Reports
        </button>

        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <ShieldCheck size={18} className="text-on-surface" />
              <span className="text-[11px] font-mono text-on-surface-variant tracking-widest uppercase">
                {standardLabels[report.standard] || report.standard}
              </span>
            </div>
            <h1 className="text-3xl font-semibold text-on-surface tracking-tight">
              {report.title}
            </h1>
            <div className="flex items-center gap-4 mt-2 text-[11px] font-mono text-on-surface-variant">
              <span>Engagement: {report.engagement_id}</span>
              <span>Generated: {new Date(report.created_at).toLocaleDateString()}</span>
              <span
                className="px-2 py-0.5 border"
                style={{
                  color:
                    report.status === "ready"
                      ? "#00FF88"
                      : report.status === "failed"
                        ? "#FF4444"
                        : "var(--prism-cyan)",
                  borderColor: "var(--border-outline-variant)",
                }}
              >
                {report.status.toUpperCase()}
              </span>
            </div>
          </div>

          {report.status === "ready" && (
            <button
              onClick={handleDownload}
              className="flex items-center gap-2 px-5 py-2.5 bg-prism-cream text-void font-bold text-xs tracking-widest uppercase hover:opacity-90 transition-all shadow-glow"
            >
              <Download size={14} />
              DOWNLOAD HTML
            </button>
          )}
        </div>
      </div>

      {/* Report Content */}
      {report.status === "generating" && (
        <div className="border border-outline-variant bg-surface/20 p-12 text-center">
          <Loader2 className="h-8 w-8 animate-spin text-prism-cyan mx-auto mb-4" />
          <p className="text-on-surface-variant text-sm tracking-widest uppercase">
            Generating compliance report...
          </p>
        </div>
      )}

      {report.status === "failed" && (
        <div className="border border-red-500/30 bg-red-500/5 p-8 text-center">
          <AlertTriangle className="h-8 w-8 text-red-400 mx-auto mb-4" />
          <p className="text-red-400 text-sm tracking-widest uppercase">
            Report generation failed
          </p>
        </div>
      )}

      {report.status === "ready" && report.html_content && (
        <div className="border border-outline-variant bg-surface/20 overflow-hidden">
          <iframe
            srcDoc={report.html_content}
            className="w-full min-h-[800px] bg-white"
            title={`Compliance Report ${reportId}`}
            sandbox="allow-same-origin"
          />
        </div>
      )}

      {report.status === "ready" && !report.html_content && report.report_data && (
        <div className="border border-outline-variant bg-surface/20 p-6">
          <h3 className="text-sm font-bold text-on-surface uppercase tracking-widest mb-4">
            Report Data (JSON)
          </h3>
          <pre className="text-[12px] font-mono text-on-surface-variant overflow-auto max-h-[600px] p-4 bg-surface border border-outline-variant">
            {JSON.stringify(report.report_data, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
