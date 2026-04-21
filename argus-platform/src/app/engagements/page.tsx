"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSession, signIn } from "next-auth/react";
import { useToast } from "@/components/ui/Toast";
import { 
  Shield, 
  Globe, 
  GitBranch, 
  AlertTriangle, 
  Loader2, 
  Target,
  ArrowRight,
  ShieldCheck
} from "lucide-react";
import MatrixDataRain from "@/components/effects/MatrixDataRain";

export default function EngagementsPage() {
  const router = useRouter();
  const { data: session, status } = useSession();
  const { showToast } = useToast();
  
  const [scanType, setScanType] = useState<"url" | "repo">("url");
  const [target, setTarget] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [progressStep, setProgressStep] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (status === "unauthenticated") {
      signIn();
    }
  }, [status, router]);

  if (status === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center bg-void text-prism-cream">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  if (!session) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);
    setProgressStep("Initializing...");

    if (!target) {
      setError("Target identifier required");
      setIsLoading(false);
      setProgressStep("");
      return;
    }

    try {
      setProgressStep("Validating target...");
      
      // Validate URL format first
      let validatedScope;
      try {
        validatedScope = scanType === "url"
          ? { domains: [new URL(target.startsWith('http') ? target : `https://${target}`).hostname], ipRanges: [] }
          : { domains: [], ipRanges: [] };
      } catch {
        throw new Error("Invalid target format");
      }

      setProgressStep("Creating engagement...");
      const response = await fetch("/api/engagement/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          targetUrl: target,
          scanType: scanType,
          authorization: "AUTHORIZED OPERATIONAL SCAN",
          authorizedScope: validatedScope,
        }),
      });

      if (response.status === 401) {
        signIn();
        return;
      }

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Failed to initiate engagement");
      }

      const engagementId = data.engagement?.id || data.engagement_id;
      
      // Validate engagement ID before redirecting
      if (!engagementId) {
        throw new Error("Invalid engagement response - no ID received");
      }
      
      setProgressStep("Redirecting to dashboard...");
      showToast("success", "Operation initiated");
      router.push(`/dashboard?engagement=${engagementId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Handshake failed");
      showToast("error", err instanceof Error ? err.message : "System failure");
    } finally {
      setIsLoading(false);
      setProgressStep("");
    }
  };

  return (
    <div className="fixed inset-0 flex items-center justify-center overflow-hidden bg-void">
      <div className="absolute inset-0 z-0 opacity-20">
        <MatrixDataRain />
      </div>

      <div className="relative z-10 w-full max-w-xl mx-4">
        {/* Header */}
        <div className="text-center mb-10">
          <div className="w-14 h-14 mx-auto mb-4 border border-prism-cream/20 bg-surface/10 flex items-center justify-center">
            <ShieldCheck size={28} className="text-prism-cream" />
          </div>
          <h1 className="text-4xl font-semibold text-text-primary tracking-tight uppercase italic font-mono">
            INITIATE ENGAGEMENT
          </h1>
          <p className="text-[11px] text-text-secondary mt-3 font-mono tracking-[0.3em] uppercase font-bold opacity-80">
            Define Operational Parameters
          </p>
        </div>

        <div className="border border-structural bg-surface/80 backdrop-blur-xl p-8">
          {/* Scan Type */}
          <div className="grid grid-cols-2 gap-4 mb-8">
            <button
              onClick={() => setScanType("url")}
              className={`flex flex-col items-center gap-3 p-6 border transition-all ${
                scanType === "url" 
                  ? "border-prism-cream bg-prism-cream/10 shadow-glow-cream" 
                  : "border-structural bg-surface/30 hover:border-text-secondary/20"
              }`}
            >
              <Globe size={24} className={scanType === "url" ? "text-prism-cream" : "text-text-secondary"} />
              <span className={`text-[10px] font-bold uppercase tracking-widest ${scanType === "url" ? "text-text-primary" : "text-text-secondary"}`}>WEB APPLICATION</span>
            </button>
            <button
              onClick={() => setScanType("repo")}
              className={`flex flex-col items-center gap-3 p-6 border transition-all ${
                scanType === "repo" 
                  ? "border-prism-cyan bg-prism-cyan/10 shadow-glow-cyan" 
                  : "border-structural bg-surface/30 hover:border-text-secondary/20"
              }`}
            >
              <GitBranch size={24} className={scanType === "repo" ? "text-prism-cyan" : "text-text-secondary"} />
              <span className={`text-[10px] font-bold uppercase tracking-widest ${scanType === "repo" ? "text-text-primary" : "text-text-secondary"}`}>REPOSITORY</span>
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label className="block text-[10px] font-bold text-text-secondary uppercase tracking-[0.2em] mb-3">
                Target Identifier
              </label>
              <div className="relative">
                <Target className="absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-text-secondary" />
                <input
                  type="text"
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  placeholder={scanType === "url" ? "https://target.com" : "username/repository"}
                  className="w-full pl-12 pr-4 py-4 bg-surface/50 border border-structural text-sm font-mono text-text-primary outline-none focus:border-prism-cream transition-colors placeholder:text-text-secondary/40 font-bold"
                  required
                />
              </div>
              {error && (
                <p className="mt-3 text-[10px] font-mono text-red-500 uppercase tracking-widest font-bold">
                  !!! {error} !!!
                </p>
              )}
            </div>

            <button
              type="submit"
              disabled={isLoading || !target}
              className={`w-full flex items-center justify-center gap-2 py-4 text-xs font-bold transition-all duration-200 group relative uppercase tracking-[0.3em] shadow-glow-cream ${
                isLoading 
                  ? "bg-transparent text-prism-cream border border-prism-cream/40" 
                  : "bg-prism-cream text-void hover:bg-white"
              }`}
            >
              {isLoading ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  AUTHORIZING...
                </span>
              ) : (
                <>
                  LAUNCH ENGAGEMENT
                  <ArrowRight size={16} className="group-hover:translate-x-1 transition-transform" />
                </>
              )}
            </button>
            
            {/* Progress Bar */}
            {isLoading && progressStep && (
              <div className="mt-3">
                <div className="flex items-center justify-between text-[9px] font-mono text-text-secondary uppercase tracking-wider mb-1">
                  <span className="animate-pulse">{progressStep}</span>
                  <span>INITIATING</span>
                </div>
                <div className="h-0.5 w-full bg-surface/30 overflow-hidden">
                  <div 
                    className="h-full bg-prism-cream animate-pulse"
                    style={{ width: "100%", animation: "progress 1.5s ease-in-out infinite" }}
                  />
                </div>
              </div>
            )}
          </form>

          <div className="mt-8 flex items-center gap-3 text-[10px] text-text-secondary font-mono italic uppercase tracking-wider font-bold">
            <AlertTriangle size={14} className="text-prism-cream" />
            Authorized operators only - system logging active
          </div>
        </div>
      </div>
    </div>
  );
}
