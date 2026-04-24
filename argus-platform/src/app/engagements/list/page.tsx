"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  Loader2,
  Plus,
  Trash2,
  Eye,
  Search,
  MoreVertical,
  GitBranch,
  Globe,
  StopCircle,
} from "lucide-react";

interface Engagement {
  id: string;
  target_url: string;
  status: string;
  scan_type: string;
  created_at: string;
  completed_at: string | null;
  created_by_email: string;
  findings_count: number;
  critical_count: number;
}

const statusColors: Record<string, string> = {
  created: "bg-blue-500/20 text-blue-400",
  recon: "bg-yellow-500/20 text-yellow-400",
  awaiting_approval: "bg-purple-500/20 text-purple-400",
  scanning: "bg-orange-500/20 text-orange-400",
  analyzing: "bg-cyan-500/20 text-cyan-400",
  reporting: "bg-pink-500/20 text-pink-400",
  complete: "bg-green-500/20 text-green-400",
  failed: "bg-red-500/20 text-red-400",
  paused: "bg-gray-500/20 text-gray-400",
};

  const getScanProgress = (status: string) => {
    const order = ["created", "recon", "awaiting_approval", "scanning", "analyzing", "reporting", "complete"];
    const idx = order.indexOf(status);
    if (idx === -1) return 0;
    return Math.round(((idx + 1) / order.length) * 100);
  };

export default function EngagementsListPage() {
  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [stoppingId, setStoppingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    if (status === "unauthenticated") {
      signIn();
    }
  }, [status]);

  useEffect(() => {
    if (status !== "authenticated") return;

    const fetchEngagements = async () => {
      setIsLoading(true);
      try {
        const response = await fetch(`/api/engagements?page=${page}&limit=10`);
        if (response.ok) {
          const data = await response.json();
          setEngagements(data.engagements || []);
          setTotalPages(data.meta?.totalPages || 1);
        }
      } catch (err) {
        showToast("error", "Failed to load engagements");
      } finally {
        setIsLoading(false);
      }
    };

    fetchEngagements();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, page]);

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this engagement and all its findings?")) return;
    setDeletingId(id);
    try {
      const response = await fetch(`/api/engagement/${id}/delete`, {
        method: "DELETE",
      });
      if (response.ok) {
        showToast("success", "Engagement deleted");
        setEngagements((prev) => prev.filter((e) => e.id !== id));
        // Refresh list from server to ensure sync
        const res = await fetch(`/api/engagements?page=${page}&limit=10`, { cache: "no-store" });
        if (res.ok) {
          const data = await res.json();
          setEngagements(data.engagements || []);
          setTotalPages(data.meta?.totalPages || 1);
        }
      } else {
        showToast("error", "Cannot delete engagement in progress");
      }
    } catch (err) {
      showToast("error", "Failed to delete engagement");
    } finally {
      setDeletingId(null);
    }
  };

  const handleStop = async (id: string) => {
    if (!confirm("Stop this scan?")) return;
    setStoppingId(id);
    try {
      const response = await fetch(`/api/engagement/${id}/stop`, {
        method: "POST",
      });
      if (response.ok) {
        showToast("success", "Scan stopped");
        // Refresh engagements
        const res = await fetch(`/api/engagements?page=${page}&limit=10`);
        if (res.ok) {
          const data = await res.json();
          setEngagements(data.engagements || []);
          setTotalPages(data.meta?.totalPages || 1);
        }
      } else {
        const data = await response.json();
        showToast("error", data.error || "Failed to stop scan");
      }
    } catch (err) {
      showToast("error", "Failed to stop scan");
    } finally {
      setStoppingId(null);
    }
  };
  
  if (status === "loading" || isLoading) {
    return (
      <div className="min-h-screen bg-background dark:bg-[#0A0A0F] p-8">
        <div className="max-w-6xl mx-auto">
          <Skeleton className="w-[200px] h-8 mb-6" />
          <div className="space-y-4">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="w-full h-20" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!session) return null;

  return (
    <div className="min-h-screen bg-background dark:bg-[#0A0A0F] p-8">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-3xl font-bold">Engagements</h1>
          <button
            onClick={() => router.push("/engagements")}
            className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-lg font-medium hover:opacity-90"
          >
            <Plus className="h-4 w-4" />
            New Scan
          </button>
        </div>

        {/* Search */}
        <div className="relative mb-6">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search engagements..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2 bg-background border border-border rounded-lg"
          />
        </div>

        {/* Engagements List */}
        <div className="space-y-4">
          {engagements.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              No engagements yet. Create your first scan!
            </div>
          ) : (
            engagements.map((eng) => (
              <div
                key={eng.id}
                className="p-4 rounded-lg border border-border bg-card hover:border-primary/50 transition-colors"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    {eng.scan_type === "repo" ? (
                      <GitBranch className="h-5 w-5 text-primary" />
                    ) : (
                      <Globe className="h-5 w-5 text-primary" />
                    )}
                    <div>
                      <p className="font-medium break-all">{eng.target_url}</p>
                      <p className="text-sm text-muted-foreground">
                        {new Date(eng.created_at).toLocaleDateString()} •{" "}
                        {eng.created_by_email}
                      </p>
                    </div>
                  </div>

                    <div className="flex items-center gap-3">
                    <span
                      className={`px-2 py-1 rounded text-xs ${statusColors[eng.status] || "bg-gray-500/20"}`}
                    >
                      {eng.status.replace(/_/g, " ")}
                    </span>

                    {/* Progress bar */}
                    <div className="flex-1 max-w-[200px]">
                      <div className="flex items-center justify-between text-[9px] text-muted-foreground mb-1">
                        <span>Progress</span>
                        <span>{getScanProgress(eng.status)}%</span>
                      </div>
                      <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                        <motion.div
                          className="h-full bg-primary rounded-full"
                          initial={{ width: 0 }}
                          animate={{ width: `${getScanProgress(eng.status)}%` }}
                          transition={{ duration: 0.6, ease: "easeOut" }}
                        />
                      </div>
                    </div>

                    <div className="flex gap-1">
                      {["recon", "scanning", "analyzing", "reporting"].includes(eng.status) && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleStop(eng.id);
                          }}
                          disabled={stoppingId === eng.id}
                          className="p-2 hover:bg-error/10 rounded text-error transition-all duration-300"
                          title="Stop scan"
                        >
                          {stoppingId === eng.id ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <StopCircle className="h-4 w-4" />
                          )}
                        </button>
                      )}
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          router.push(`/dashboard?engagement=${eng.id}`);
                        }}
                        className="p-2 hover:bg-muted rounded"
                        title="View"
                      >
                        <Eye className="h-4 w-4" />
                      </button>
                      <button
                        onClick={(e) => handleDelete(eng.id)}
                        className="p-2 hover:bg-red-500/10 rounded text-red-400"
                        title="Delete"
                      >
                        {deletingId === eng.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Trash2 className="h-4 w-4" />
                        )}
                      </button>
                    </div>
                  </div>
                </div>

                {/* Stats */}
                <div className="flex gap-4 mt-3 text-sm text-muted-foreground">
                  <span>{eng.findings_count} findings</span>
                  {eng.critical_count > 0 && (
                    <span className="text-red-400">
                      {eng.critical_count} critical
                    </span>
                  )}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2 mt-6">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1 border rounded disabled:opacity-50"
            >
              Previous
            </button>
            <span className="text-sm">
              Page {page} of {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="px-3 py-1 border rounded disabled:opacity-50"
            >
              Next
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
