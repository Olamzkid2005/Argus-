"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { FindingFilters } from "@/components/ui/FindingFilters";
import { FindingCard } from "@/components/ui/FindingCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { Loader2, ShieldAlert, Search } from "lucide-react";

interface Finding {
  id: string;
  type: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
  endpoint: string;
  source_tool: string;
  verified: boolean;
  confidence?: number;
  created_at: string;
  evidence?: Record<string, unknown>;
}

export default function FindingsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { data: session, status } = useSession();
  const { showToast } = useToast();
  const [findings, setFindings] = useState<Finding[]>([]);
  const [filteredFindings, setFilteredFindings] = useState<Finding[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (status === "unauthenticated") {
      signIn();
    }
  }, [status]);

  useEffect(() => {
    if (status !== "authenticated") return;

    const fetchFindings = async () => {
      setIsLoading(true);
      try {
        const response = await fetch("/api/findings?limit=100");
        if (response.ok) {
          const data = await response.json();
          setFindings(data.findings || []);
          setFilteredFindings(data.findings || []);
        }
      } catch (err) {
        showToast("error", "Failed to load findings");
      } finally {
        setIsLoading(false);
      }
    };

    fetchFindings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  const handleFilterChange = (filtered: Finding[]) => {
    setFilteredFindings(filtered);
  };

  const handleVerify = async (id: string) => {
    try {
      const response = await fetch(`/api/findings/${id}/verify`, {
        method: "POST",
      });
      if (response.ok) {
        showToast("success", "Finding verified!");
        setFindings((prev) =>
          prev.map((f) => (f.id === id ? { ...f, verified: true } : f)),
        );
      }
    } catch (err) {
      showToast("error", "Failed to verify finding");
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Are you sure you want to delete this finding?")) return;

    try {
      const response = await fetch(`/api/findings/${id}`, {
        method: "DELETE",
      });
      if (response.ok) {
        showToast("success", "Finding deleted");
        setFindings((prev) => prev.filter((f) => f.id !== id));
        setFilteredFindings((prev) => prev.filter((f) => f.id !== id));
      }
    } catch (err) {
      showToast("error", "Failed to delete finding");
    }
  };

  if (status === "loading" || isLoading) {
    return (
      <div className="min-h-screen p-8">
        <div className="max-w-6xl mx-auto space-y-6">
          <Skeleton width={200} height={32} />
          <Skeleton width="100%" height={400} />
        </div>
      </div>
    );
  }

  if (!session) {
    return null;
  }

  // Group findings by severity for summary
  const severityCounts = findings.reduce(
    (acc, f) => {
      acc[f.severity] = (acc[f.severity] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>,
  );

  return (
    <div className="min-h-screen p-8">
      <div className="max-w-6xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Findings</h1>
            <p className="text-muted-foreground mt-1">
              {findings.length} total vulnerabilities discovered
            </p>
          </div>
        </div>

        {/* Severity Summary */}
        <div className="grid grid-cols-5 gap-4">
          {["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"].map((sev) => (
            <div
              key={sev}
              className={`p-4 rounded-lg border ${
                sev === "CRITICAL"
                  ? "bg-red-500/10 border-red-500/30"
                  : sev === "HIGH"
                    ? "bg-orange-500/10 border-orange-500/30"
                    : sev === "MEDIUM"
                      ? "bg-yellow-500/10 border-yellow-500/30"
                      : sev === "LOW"
                        ? "bg-blue-500/10 border-blue-500/30"
                        : "bg-gray-500/10 border-gray-500/30"
              }`}
            >
              <div className="text-2xl font-bold">
                {severityCounts[sev] || 0}
              </div>
              <div className="text-sm text-muted-foreground">{sev}</div>
            </div>
          ))}
        </div>

        {/* Filters */}
        <FindingFilters findings={findings} onFilter={handleFilterChange} />

        {/* Findings List */}
        <div className="grid gap-4">
          {filteredFindings.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <ShieldAlert className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p>No findings discovered yet.</p>
              <p className="text-sm mt-2">
                Create an engagement to start scanning.
              </p>
            </div>
          ) : (
            filteredFindings.map((finding) => (
              <FindingCard
                key={finding.id}
                finding={finding}
                onVerify={handleVerify}
                onDelete={handleDelete}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
