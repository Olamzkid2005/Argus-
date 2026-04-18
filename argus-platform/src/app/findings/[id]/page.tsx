"use client";

/**
 * Findings Dashboard Page
 * 
 * Displays vulnerability findings grouped by severity with filtering capabilities.
 * 
 * Requirements: 32.1, 32.2, 32.3, 32.4, 32.5
 */

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";

// Types
interface Finding {
  id: string;
  engagement_id: string;
  type: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
  confidence: number;
  endpoint: string;
  evidence: Record<string, unknown>;
  source_tool: string;
  created_at: string;
  repro_steps?: string[];
  cvss_score?: number;
  owasp_category?: string;
  cwe_id?: string;
}

interface ExecutionSpan {
  id: string;
  trace_id: string;
  span_name: string;
  duration_ms: number;
  created_at: string;
}

export default function FindingsDashboardPage() {
  const params = useParams();
  const engagementId = params.id as string;

  const [findings, setFindings] = useState<Finding[]>([]);
  const [timeline, setTimeline] = useState<ExecutionSpan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filter state
  const [selectedSeverities, setSelectedSeverities] = useState<string[]>([]);
  const [minConfidence, setMinConfidence] = useState<number>(0);
  const [selectedTools, setSelectedTools] = useState<string[]>([]);

  // Fetch findings
  useEffect(() => {
    if (!engagementId) return;

    const fetchFindings = async () => {
      try {
        setLoading(true);
        setError(null);

        // Build query parameters
        const params = new URLSearchParams();
        if (selectedSeverities.length > 0) {
          params.set("severity", selectedSeverities.join(","));
        }
        if (minConfidence > 0) {
          params.set("minConfidence", minConfidence.toString());
        }
        if (selectedTools.length > 0) {
          params.set("sourceTool", selectedTools.join(","));
        }

        const response = await fetch(
          `/api/engagement/${engagementId}/findings?${params.toString()}`
        );

        if (!response.ok) {
          throw new Error("Failed to fetch findings");
        }

        const data = await response.json();
        setFindings(data.findings || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unknown error");
      } finally {
        setLoading(false);
      }
    };

    fetchFindings();
  }, [engagementId, selectedSeverities, minConfidence, selectedTools]);

  // Fetch timeline
  useEffect(() => {
    if (!engagementId) return;

    const fetchTimeline = async () => {
      try {
        const response = await fetch(`/api/engagement/${engagementId}/timeline`);
        if (response.ok) {
          const data = await response.json();
          setTimeline(data.spans || []);
        }
      } catch (err) {
        console.error("Failed to fetch timeline:", err);
      }
    };

    fetchTimeline();
  }, [engagementId]);

  // Group findings by severity
  const groupedFindings = findings.reduce(
    (acc, finding) => {
      const severity = finding.severity;
      if (!acc[severity]) {
        acc[severity] = [];
      }
      acc[severity].push(finding);
      return acc;
    },
    {} as Record<string, Finding[]>
  );

  // Get unique tools for filter
  const availableTools = Array.from(
    new Set(findings.map((f) => f.source_tool))
  ).sort();

  // Severity order for display
  const severityOrder: Array<"CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO"> = [
    "CRITICAL",
    "HIGH",
    "MEDIUM",
    "LOW",
    "INFO",
  ];

  // Get severity color
  const getSeverityColor = (severity: string): string => {
    switch (severity) {
      case "CRITICAL":
        return "bg-red-900/50 text-red-300 border-red-700";
      case "HIGH":
        return "bg-orange-900/50 text-orange-300 border-orange-700";
      case "MEDIUM":
        return "bg-yellow-900/50 text-yellow-300 border-yellow-700";
      case "LOW":
        return "bg-blue-900/50 text-blue-300 border-blue-700";
      case "INFO":
        return "bg-gray-700 text-gray-300 border-gray-600";
      default:
        return "bg-gray-700 text-gray-300 border-gray-600";
    }
  };

  // Toggle severity filter
  const toggleSeverity = (severity: string) => {
    setSelectedSeverities((prev) =>
      prev.includes(severity)
        ? prev.filter((s) => s !== severity)
        : [...prev, severity]
    );
  };

  // Toggle tool filter
  const toggleTool = (tool: string) => {
    setSelectedTools((prev) =>
      prev.includes(tool) ? prev.filter((t) => t !== tool) : [...prev, tool]
    );
  };

  return (
    <div className="min-h-screen bg-slate-900 text-white">
      {/* Header */}
      <header className="border-b border-slate-700 px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Findings Dashboard</h1>
            <p className="text-slate-400 text-sm">
              Engagement: {engagementId}
            </p>
          </div>
          <div className="flex items-center gap-4">
            <a
              href="/dashboard"
              className="px-4 py-2 bg-slate-700 rounded-lg hover:bg-slate-600 transition-colors text-sm"
            >
              Real-Time Monitor
            </a>
            <a
              href="/"
              className="px-4 py-2 bg-slate-700 rounded-lg hover:bg-slate-600 transition-colors text-sm"
            >
              Home
            </a>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        {/* Filters */}
        <div className="mb-8 p-6 bg-slate-800 rounded-lg border border-slate-700">
          <h2 className="text-lg font-semibold mb-4">Filters</h2>

          {/* Severity Filter */}
          <div className="mb-4">
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Severity
            </label>
            <div className="flex flex-wrap gap-2">
              {severityOrder.map((severity) => (
                <button
                  key={severity}
                  onClick={() => toggleSeverity(severity)}
                  className={`px-3 py-1 rounded-lg text-sm font-medium transition-colors border ${
                    selectedSeverities.includes(severity)
                      ? getSeverityColor(severity)
                      : "bg-slate-700 text-slate-300 border-slate-600 hover:bg-slate-600"
                  }`}
                >
                  {severity}
                </button>
              ))}
            </div>
          </div>

          {/* Confidence Filter */}
          <div className="mb-4">
            <label
              htmlFor="confidence-filter"
              className="block text-sm font-medium text-slate-300 mb-2"
            >
              Minimum Confidence: {minConfidence}%
            </label>
            <input
              id="confidence-filter"
              type="range"
              min="0"
              max="100"
              step="5"
              value={minConfidence}
              onChange={(e) => setMinConfidence(parseInt(e.target.value))}
              className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer"
            />
          </div>

          {/* Tool Filter */}
          {availableTools.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Source Tool
              </label>
              <div className="flex flex-wrap gap-2">
                {availableTools.map((tool) => (
                  <button
                    key={tool}
                    onClick={() => toggleTool(tool)}
                    className={`px-3 py-1 rounded-lg text-sm font-medium transition-colors border ${
                      selectedTools.includes(tool)
                        ? "bg-purple-900/50 text-purple-300 border-purple-700"
                        : "bg-slate-700 text-slate-300 border-slate-600 hover:bg-slate-600"
                    }`}
                  >
                    {tool}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Summary Stats */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
          {severityOrder.map((severity) => (
            <div
              key={severity}
              className={`p-4 rounded-lg border ${getSeverityColor(severity)}`}
            >
              <p className="text-sm font-medium">{severity}</p>
              <p className="text-2xl font-bold">
                {groupedFindings[severity]?.length || 0}
              </p>
            </div>
          ))}
        </div>

        {/* Loading State */}
        {loading && (
          <div className="text-center py-12">
            <p className="text-slate-400">Loading findings...</p>
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="p-4 bg-red-900/20 border border-red-700 rounded-lg mb-8">
            <p className="text-red-300">Error: {error}</p>
          </div>
        )}

        {/* Findings by Severity */}
        {!loading && !error && (
          <div className="space-y-6">
            {severityOrder.map((severity) => {
              const severityFindings = groupedFindings[severity] || [];
              if (severityFindings.length === 0) return null;

              return (
                <div key={severity} className="bg-slate-800 rounded-lg border border-slate-700">
                  <div className={`px-6 py-4 border-b border-slate-700 ${getSeverityColor(severity)}`}>
                    <h2 className="text-lg font-semibold">
                      {severity} ({severityFindings.length})
                    </h2>
                  </div>
                  <div className="divide-y divide-slate-700">
                    {severityFindings.map((finding) => (
                      <FindingCard key={finding.id} finding={finding} />
                    ))}
                  </div>
                </div>
              );
            })}

            {findings.length === 0 && (
              <div className="text-center py-12 text-slate-400">
                No findings match the current filters.
              </div>
            )}
          </div>
        )}

        {/* Execution Timeline */}
        {timeline.length > 0 && (
          <div className="mt-8 bg-slate-800 rounded-lg border border-slate-700">
            <div className="px-6 py-4 border-b border-slate-700">
              <h2 className="text-lg font-semibold">Execution Timeline</h2>
            </div>
            <div className="divide-y divide-slate-700 max-h-96 overflow-y-auto">
              {timeline.map((span) => (
                <div key={span.id} className="px-6 py-3 flex items-center justify-between">
                  <div className="flex-1">
                    <p className="text-sm font-medium text-white">{span.span_name}</p>
                    <p className="text-xs text-slate-400">
                      {new Date(span.created_at).toLocaleString()}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-medium text-blue-300">
                      {span.duration_ms}ms
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

/**
 * Finding Card Component
 * 
 * Requirements: 32.3, 32.4
 */
function FindingCard({ finding }: { finding: Finding }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="px-6 py-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-3 mb-2">
            <h3 className="text-base font-semibold text-white">{finding.type}</h3>
            <span className="px-2 py-0.5 bg-purple-900/50 text-purple-300 rounded text-xs font-medium">
              {finding.source_tool}
            </span>
          </div>
          <p className="text-sm text-slate-300 mb-2 break-all">{finding.endpoint}</p>
          <div className="flex items-center gap-4 text-xs text-slate-400">
            <span>
              Confidence:{" "}
              <span className="text-white font-medium">
                {(finding.confidence * 100).toFixed(0)}%
              </span>
            </span>
            {finding.cvss_score && (
              <span>
                CVSS:{" "}
                <span className="text-white font-medium">
                  {finding.cvss_score.toFixed(1)}
                </span>
              </span>
            )}
            {finding.cwe_id && (
              <span>
                CWE:{" "}
                <span className="text-white font-medium">{finding.cwe_id}</span>
              </span>
            )}
            {finding.owasp_category && (
              <span>
                OWASP:{" "}
                <span className="text-white font-medium">
                  {finding.owasp_category}
                </span>
              </span>
            )}
          </div>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="px-3 py-1 bg-slate-700 rounded hover:bg-slate-600 transition-colors text-sm"
        >
          {expanded ? "Hide" : "Details"}
        </button>
      </div>

      {/* Expanded Details */}
      {expanded && (
        <div className="mt-4 pt-4 border-t border-slate-700 space-y-3">
          {/* Evidence */}
          {finding.evidence && Object.keys(finding.evidence).length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-slate-300 mb-2">Evidence</h4>
              <pre className="text-xs bg-slate-900 p-3 rounded overflow-x-auto text-slate-300">
                {JSON.stringify(finding.evidence, null, 2)}
              </pre>
            </div>
          )}

          {/* Reproduction Steps */}
          {finding.repro_steps && finding.repro_steps.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-slate-300 mb-2">
                Reproduction Steps
              </h4>
              <ol className="list-decimal list-inside space-y-1 text-sm text-slate-300">
                {finding.repro_steps.map((step, index) => (
                  <li key={index}>{step}</li>
                ))}
              </ol>
            </div>
          )}

          {/* Metadata */}
          <div className="text-xs text-slate-400">
            <p>
              Discovered:{" "}
              {new Date(finding.created_at).toLocaleString()}
            </p>
            <p>Finding ID: {finding.id}</p>
          </div>
        </div>
      )}
    </div>
  );
}
