"use client";

import { useState } from "react";
import {
  Trash2,
  Copy,
  ExternalLink,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

interface Finding {
  id: string;
  type: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
  endpoint: string;
  evidence?: Record<string, unknown>;
  source_tool: string;
  repro_steps?: string[];
  cvss_score?: number;
  cwe_id?: string;
  owasp_category?: string;
  verified: boolean;
  confidence?: number;
  created_at: string;
}

interface FindingCardProps {
  finding: Finding;
  onDelete?: (id: string) => void;
  onVerify?: (id: string) => void;
}

const severityColors = {
  CRITICAL: "bg-red-500/20 text-red-400 border-red-500/50",
  HIGH: "bg-orange-500/20 text-orange-400 border-orange-500/50",
  MEDIUM: "bg-yellow-500/20 text-yellow-400 border-yellow-500/50",
  LOW: "bg-blue-500/20 text-blue-400 border-blue-500/50",
  INFO: "bg-gray-500/20 text-gray-400 border-gray-500/50",
};

export function FindingCard({ finding, onDelete, onVerify }: FindingCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  const copyToClipboard = async (text: string) => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="p-4 rounded-lg border border-border bg-card hover:border-primary/50 transition-colors">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span
            className={`px-2 py-1 rounded text-xs font-medium border ${severityColors[finding.severity]}`}
          >
            {finding.severity}
          </span>
          <span className="text-sm text-muted-foreground">
            {finding.source_tool}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {finding.verified && (
            <span className="px-2 py-1 rounded text-xs bg-green-500/20 text-green-400 border border-green-500/50">
              Verified
            </span>
          )}
        </div>
      </div>

      {/* Type & Endpoint */}
      <h3 className="font-medium mt-2">{finding.type}</h3>
      <p className="text-sm text-muted-foreground font-mono mt-1 break-all">
        {finding.endpoint}
      </p>

      {/* Metrics */}
      <div className="flex items-center gap-4 mt-3 text-xs text-muted-foreground">
        {finding.cvss_score && <span>CVSS: {finding.cvss_score}</span>}
        {finding.cwe_id && <span>CWE: {finding.cwe_id}</span>}
        {finding.confidence && (
          <span>Confidence: {Math.round(finding.confidence * 100)}%</span>
        )}
      </div>

      {/* Expandable Details */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 mt-3 text-sm text-muted-foreground hover:text-primary transition-colors"
      >
        {expanded ? (
          <ChevronUp className="h-4 w-4" />
        ) : (
          <ChevronDown className="h-4 w-4" />
        )}
        {expanded ? "Hide details" : "Show details"}
      </button>

      {expanded && (
        <div className="mt-4 space-y-4 pt-4 border-t border-border">
          {/* Evidence */}
          {finding.evidence && (
            <div>
              <h4 className="text-sm font-medium mb-2">Evidence</h4>
              <pre className="text-xs bg-muted p-3 rounded-lg overflow-x-auto">
                {JSON.stringify(finding.evidence, null, 2)}
              </pre>
            </div>
          )}

          {/* Repro Steps */}
          {finding.repro_steps && finding.repro_steps.length > 0 && (
            <div>
              <h4 className="text-sm font-medium mb-2">Reproduction Steps</h4>
              <ol className="text-sm text-muted-foreground space-y-1">
                {finding.repro_steps.map((step, i) => (
                  <li key={i}>
                    {i + 1}. {step}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Actions */}
          <div className="flex flex-wrap gap-2 pt-2">
            <button
              onClick={() => copyToClipboard(finding.endpoint)}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs bg-muted hover:bg-muted/80 transition-colors"
            >
              <Copy className="h-3 w-3" />
              {copied ? "Copied!" : "Copy"}
            </button>

            <button
              onClick={() => window.open(finding.endpoint, "_blank")}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs bg-muted hover:bg-muted/80 transition-colors"
            >
              <ExternalLink className="h-3 w-3" />
              Visit
            </button>

            {onVerify && !finding.verified && (
              <button
                onClick={() => onVerify(finding.id)}
                className="px-3 py-1.5 rounded-lg text-xs bg-green-500/20 text-green-400 hover:bg-green-500/30 transition-colors"
              >
                Verify
              </button>
            )}

            {onDelete && (
              <button
                onClick={() => onDelete(finding.id)}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors"
              >
                <Trash2 className="h-3 w-3" />
                Delete
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
