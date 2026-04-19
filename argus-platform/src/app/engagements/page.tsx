"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  Globe,
  GitBranch,
  Shield,
  AlertTriangle,
  Loader2,
  CheckCircle,
  XCircle,
} from "lucide-react";

export default function EngagementsPage() {
  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();
  const [scanType, setScanType] = useState<"url" | "repo">("url");
  const [target, setTarget] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  // Redirect to signin if not authenticated
  useEffect(() => {
    if (status === "unauthenticated") {
      signIn();
    }
  }, [status]);

  if (status === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!session) {
    return null; // Will redirect via useEffect
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);

    if (!target) {
      setError("Please enter a target URL");
      setIsLoading(false);
      showToast("error", "Please enter a target URL");
      return;
    }

    try {
      const response = await fetch("/api/engagement/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          targetUrl: target,
          scanType: scanType,
          authorization: "Authorized scan",
          authorizedScope:
            scanType === "url"
              ? { domains: [new URL(target).hostname], ipRanges: [] }
              : { domains: [], ipRanges: [] },
        }),
      });

      if (response.status === 401) {
        signIn();
        return;
      }

      if (!response.ok) {
        const data = await response.json();
        setError(data.error || `Server error: ${response.status}`);
        showToast("error", data.error || `Failed to create engagement`);
        setIsLoading(false);
        return;
      }

      const data = await response.json();
      const engagementId = data.engagement?.id || data.engagement_id;

      if (!engagementId) {
        setError("Invalid response from server - no engagement ID");
        showToast("error", "Invalid response from server");
        setIsLoading(false);
        return;
      }

      showToast("success", "Engagement created successfully!");
      router.push(`/dashboard?engagement=${engagementId}`);
    } catch (err) {
      if (err instanceof TypeError && err.message.includes("fetch")) {
        setError("Network error - please check your connection");
        showToast("error", "Network error");
      } else {
        setError(err instanceof Error ? err.message : "Something went wrong");
        showToast(
          "error",
          err instanceof Error ? err.message : "Something went wrong",
        );
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="w-full max-w-lg">
        <div className="text-center mb-8">
          <Shield className="h-12 w-12 mx-auto text-primary mb-4" />
          <h1 className="text-3xl font-bold bg-gradient-to-br from-accent to-primary bg-clip-text text-transparent">
            New Engagement
          </h1>
          <p className="text-muted-foreground mt-2">
            Scan a web application or repository
          </p>
        </div>

        <div className="prism-glass rounded-2xl p-6">
          {/* Scan Type Selector */}
          <div className="grid grid-cols-2 gap-3 mb-6">
            <button
              type="button"
              onClick={() => setScanType("url")}
              className={`p-4 rounded-xl border transition-all ${
                scanType === "url"
                  ? "border-primary bg-primary/10"
                  : "border-border hover:border-primary/50"
              }`}
            >
              <Globe className="h-6 w-6 mx-auto mb-2" />
              <span className="block font-medium">Web App</span>
              <span className="block text-xs text-muted-foreground">
                URL or Domain
              </span>
            </button>

            <button
              type="button"
              onClick={() => setScanType("repo")}
              className={`p-4 rounded-xl border transition-all ${
                scanType === "repo"
                  ? "border-primary bg-primary/10"
                  : "border-border hover:border-primary/50"
              }`}
            >
              <GitBranch className="h-6 w-6 mx-auto mb-2" />
              <span className="block font-medium">Repository</span>
              <span className="block text-xs text-muted-foreground">
                GitHub/GitLab
              </span>
            </button>
          </div>

          <form onSubmit={handleSubmit}>
            <div className="mb-4">
              <label className="block text-sm font-medium mb-2">
                {scanType === "url" ? "Target URL" : "Repository URL"}
              </label>
              <input
                type="text"
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                placeholder={
                  scanType === "url"
                    ? "https://example.com"
                    : "https://github.com/username/repo"
                }
                className="w-full px-4 py-3 rounded-xl bg-background border border-border focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-all"
                required
              />
              {scanType === "repo" && (
                <p className="text-xs text-muted-foreground mt-2 flex items-center gap-1">
                  <AlertTriangle className="h-3 w-3" />
                  Repo must be public or you need to configure credentials
                </p>
              )}
            </div>

            {error && (
              <div className="mb-4 p-3 rounded-lg bg-destructive/10 text-destructive text-sm">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={isLoading || !target}
              className="w-full py-3 px-4 rounded-xl bg-gradient-to-r from-primary to-accent text-white font-medium hover:opacity-90 disabled:opacity-50 transition-all flex items-center justify-center gap-2"
            >
              {isLoading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Creating Engagement...
                </>
              ) : (
                <>
                  <Shield className="h-4 w-4" />
                  Start Scan
                </>
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
