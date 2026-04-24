import React, { useState } from "react";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";
import {
  Shield,
  FileText,
  Wrench,
  BookOpen,
  Code,
  Copy,
  Check,
} from "lucide-react";

export interface Finding {
  id: string;
  type: string;
  severity: string;
  endpoint: string;
  description?: string;
  evidence?: Record<string, any>;
  recommendation?: string;
  references?: string[];
  cve?: string;
  cwe?: string;
  confidence?: number;
  created_at?: string;
}

interface FindingTabsProps {
  finding: Finding;
}

function SeverityBadge({ severity }: { severity: string }) {
  const colors: Record<string, string> = {
    CRITICAL: "bg-red-100 text-red-800 border-red-200",
    HIGH: "bg-orange-100 text-orange-800 border-orange-200",
    MEDIUM: "bg-yellow-100 text-yellow-800 border-yellow-200",
    LOW: "bg-blue-100 text-blue-800 border-blue-200",
    INFO: "bg-gray-100 text-gray-800 border-gray-200",
  };

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${colors[severity] || colors.INFO}`}
    >
      {severity}
    </span>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="ml-2 p-1 rounded hover:bg-gray-100 transition-colors"
      aria-label={copied ? "Copied" : "Copy to clipboard"}
      title={copied ? "Copied!" : "Copy"}
    >
      {copied ? (
        <Check className="w-3.5 h-3.5 text-green-600" />
      ) : (
        <Copy className="w-3.5 h-3.5 text-gray-400" />
      )}
    </button>
  );
}

function EvidenceItem({
  label,
  value,
}: {
  label: string;
  value: any;
}) {
  const displayValue =
    typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);

  return (
    <div className="border-b border-gray-100 last:border-0 py-3">
      <div className="flex items-center justify-between">
        <dt className="text-sm font-medium text-gray-500">{label}</dt>
        <CopyButton text={displayValue} />
      </div>
      <dd className="mt-1 text-sm text-gray-900 font-mono bg-gray-50 rounded p-2 overflow-x-auto">
        <pre className="whitespace-pre-wrap break-all">{displayValue}</pre>
      </dd>
    </div>
  );
}

function ConfidenceBar({ confidence }: { confidence?: number }) {
  if (confidence === undefined) return null;

  const percentage = Math.round(confidence * 100);
  let color = "bg-gray-400";
  if (percentage >= 80) color = "bg-green-500";
  else if (percentage >= 60) color = "bg-yellow-500";
  else if (percentage >= 40) color = "bg-orange-500";
  else color = "bg-red-500";

  return (
    <div className="mt-2">
      <div className="flex justify-between text-xs text-gray-500 mb-1">
        <span>Confidence</span>
        <span>{percentage}%</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2">
        <div
          className={`${color} h-2 rounded-full transition-all duration-500`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

export default function FindingTabs({ finding }: FindingTabsProps) {
  const referenceLinks = [
    ...(finding.references || []),
    ...(finding.cve
      ? [`https://nvd.nist.gov/vuln/detail/${finding.cve}`]
      : []),
    ...(finding.cwe
      ? [`https://cwe.mitre.org/data/definitions/${finding.cwe.replace("CWE-", "")}.html`]
      : []),
  ];

  return (
    <Tabs defaultValue="overview" className="w-full">
      <TabsList className="grid w-full grid-cols-5" aria-label="Finding detail tabs">
        <TabsTrigger value="overview" aria-label="Overview">
          <Shield className="w-4 h-4 mr-1.5" />
          <span className="hidden sm:inline">Overview</span>
        </TabsTrigger>
        <TabsTrigger value="evidence" aria-label="Evidence">
          <FileText className="w-4 h-4 mr-1.5" />
          <span className="hidden sm:inline">Evidence</span>
        </TabsTrigger>
        <TabsTrigger value="remediation" aria-label="Remediation">
          <Wrench className="w-4 h-4 mr-1.5" />
          <span className="hidden sm:inline">Fix</span>
        </TabsTrigger>
        <TabsTrigger value="references" aria-label="References">
          <BookOpen className="w-4 h-4 mr-1.5" />
          <span className="hidden sm:inline">Refs</span>
        </TabsTrigger>
        <TabsTrigger value="technical" aria-label="Technical details">
          <Code className="w-4 h-4 mr-1.5" />
          <span className="hidden sm:inline">Raw</span>
        </TabsTrigger>
      </TabsList>

      <TabsContent value="overview" className="mt-4 space-y-4">
        <div className="bg-white rounded-lg border p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-lg font-semibold text-gray-900">
              {finding.type}
            </h3>
            <SeverityBadge severity={finding.severity} />
          </div>

          <div className="space-y-3">
            <div>
              <p className="text-sm text-gray-500">Endpoint</p>
              <p className="text-sm font-mono text-gray-900 break-all">
                {finding.endpoint}
              </p>
            </div>

            {finding.description && (
              <div>
                <p className="text-sm text-gray-500">Description</p>
                <p className="text-sm text-gray-900">{finding.description}</p>
              </div>
            )}

            <ConfidenceBar confidence={finding.confidence} />

            {finding.created_at && (
              <div>
                <p className="text-sm text-gray-500">Discovered</p>
                <p className="text-sm text-gray-900">
                  {new Date(finding.created_at).toLocaleString()}
                </p>
              </div>
            )}

            <div className="flex gap-2 pt-2">
              {finding.cve && (
                <a
                  href={`https://nvd.nist.gov/vuln/detail/${finding.cve}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center px-2 py-1 rounded text-xs font-medium bg-red-50 text-red-700 hover:bg-red-100 transition-colors"
                >
                  {finding.cve}
                </a>
              )}
              {finding.cwe && (
                <a
                  href={`https://cwe.mitre.org/data/definitions/${finding.cwe.replace("CWE-", "")}.html`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center px-2 py-1 rounded text-xs font-medium bg-blue-50 text-blue-700 hover:bg-blue-100 transition-colors"
                >
                  {finding.cwe}
                </a>
              )}
            </div>
          </div>
        </div>
      </TabsContent>

      <TabsContent value="evidence" className="mt-4">
        <div className="bg-white rounded-lg border p-4">
          {finding.evidence && Object.keys(finding.evidence).length > 0 ? (
            <dl>
              {Object.entries(finding.evidence).map(([key, value]) => (
                <EvidenceItem key={key} label={key} value={value} />
              ))}
            </dl>
          ) : (
            <p className="text-sm text-gray-500 text-center py-8">
              No evidence recorded for this finding.
            </p>
          )}
        </div>
      </TabsContent>

      <TabsContent value="remediation" className="mt-4">
        <div className="bg-white rounded-lg border p-4">
          {finding.recommendation ? (
            <div className="prose prose-sm max-w-none">
              <h4 className="text-sm font-medium text-gray-900 mb-2">
                Recommended Fix
              </h4>
              <div className="text-sm text-gray-700 whitespace-pre-wrap">
                {finding.recommendation}
              </div>
            </div>
          ) : (
            <div className="text-center py-8">
              <Wrench className="w-8 h-8 text-gray-300 mx-auto mb-2" />
              <p className="text-sm text-gray-500">
                No specific remediation guidance available.
              </p>
              <p className="text-xs text-gray-400 mt-1">
                Refer to the references tab for external resources.
              </p>
            </div>
          )}
        </div>
      </TabsContent>

      <TabsContent value="references" className="mt-4">
        <div className="bg-white rounded-lg border p-4">
          {referenceLinks.length > 0 ? (
            <ul className="space-y-2">
              {referenceLinks.map((ref, i) => (
                <li key={i}>
                  <a
                    href={ref}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-blue-600 hover:text-blue-800 hover:underline break-all flex items-start"
                  >
                    <BookOpen className="w-4 h-4 mr-2 mt-0.5 flex-shrink-0" />
                    {ref}
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-gray-500 text-center py-8">
              No references available.
            </p>
          )}
        </div>
      </TabsContent>

      <TabsContent value="technical" className="mt-4">
        <div className="bg-white rounded-lg border p-4">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-medium text-gray-900">
              Raw Finding Data
            </h4>
            <CopyButton text={JSON.stringify(finding, null, 2)} />
          </div>
          <pre className="text-xs text-gray-700 bg-gray-50 rounded p-3 overflow-x-auto">
            {JSON.stringify(finding, null, 2)}
          </pre>
        </div>
      </TabsContent>
    </Tabs>
  );
}
