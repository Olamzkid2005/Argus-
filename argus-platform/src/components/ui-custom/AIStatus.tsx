"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Brain, Zap, AlertCircle, Loader2 } from "lucide-react";

interface AIStatus {
  configured: boolean;
  model: string;
  checking: boolean;
  error: string | null;
}

export function useAIStatus() {
  const [status, setStatus] = useState<AIStatus>({
    configured: false,
    model: "",
    checking: true,
    error: null,
  });

  useEffect(() => {
    const checkAI = async () => {
      try {
        const [aiRes, settingsRes] = await Promise.all([
          fetch("/api/ai/explain"),
          fetch("/api/settings"),
        ]);

        let configured = false;
        let model = "";

        if (aiRes.ok) {
          const aiData = await aiRes.json();
          configured = aiData.configured;
          if (aiData.preferredModel) model = aiData.preferredModel;
        }

        if (settingsRes.ok) {
          const settingsData = await settingsRes.json();
          if (settingsData.settings?.preferred_ai_model) {
            model = settingsData.settings.preferred_ai_model;
          }
        }

        setStatus({ configured, model, checking: false, error: null });
      } catch (err) {
        setStatus({
          configured: false,
          model: "",
          checking: false,
          error: "Failed to check AI status",
        });
      }
    };

    checkAI();
    // Refresh every 30 seconds
    const interval = setInterval(checkAI, 30000);
    return () => clearInterval(interval);
  }, []);

  return status;
}

export function AIStatusIndicator({ showLabel = true, compact = false }: { showLabel?: boolean; compact?: boolean }) {
  const router = useRouter();
  const status = useAIStatus();

  if (status.checking) {
    return (
      <div className={`flex items-center gap-2 ${compact ? "px-2 py-1" : "px-3 py-2"} border border-structural bg-surface/30`}>
        <Loader2 size={compact ? 12 : 14} className="animate-spin text-text-secondary" />
        {showLabel && <span className="text-[10px] font-mono text-text-secondary uppercase">Checking AI...</span>}
      </div>
    );
  }

  if (!status.configured) {
    return (
      <button
        onClick={() => router.push("/settings")}
        className={`flex items-center gap-2 border border-red-500/30 bg-red-500/10 hover:bg-red-500/20 transition-all w-full text-left ${
          compact ? "px-2 py-1" : "px-3 py-2"
        }`}
        title="AI not configured - click to set up"
      >
        <AlertCircle size={compact ? 12 : 14} className="text-red-400 shrink-0" />
        {showLabel && (
          <div className="flex-1 min-w-0">
            <span className="text-[10px] font-mono text-red-400 uppercase block truncate">AI Not Configured</span>
            {!compact && <span className="text-[9px] text-text-secondary block">Click to set up</span>}
          </div>
        )}
      </button>
    );
  }

  // Extract model name from ID (e.g., "anthropic/claude-3.5-sonnet" -> "Claude 3.5 Sonnet")
  const modelName = status.model
    ? status.model
        .split("/")
        .pop()
        ?.split("-")
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(" ") || status.model
    : "Unknown";

  return (
    <div
      className={`flex items-center gap-2 border border-green-500/30 bg-green-500/10 ${
        compact ? "px-2 py-1" : "px-3 py-2"
      }`}
      title={`AI Active: ${modelName}`}
    >
      <div className="relative shrink-0">
        <Brain size={compact ? 12 : 14} className="text-green-400" />
        <div className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-green-400 rounded-full animate-pulse" />
      </div>
      {showLabel && (
        <div className="flex-1 min-w-0">
          <span className="text-[10px] font-mono text-green-400 uppercase block truncate">AI Active</span>
          {!compact && (
            <span className="text-[9px] text-text-secondary block truncate">{modelName}</span>
          )}
        </div>
      )}
    </div>
  );
}

export function AIStatusBadge() {
  const status = useAIStatus();
  const router = useRouter();

  if (status.checking) {
    return (
      <span className="inline-flex items-center gap-1.5 text-[10px] font-mono text-text-secondary">
        <Loader2 size={10} className="animate-spin" />
        AI...
      </span>
    );
  }

  if (!status.configured) {
    return (
      <button
        onClick={() => router.push("/settings")}
        className="inline-flex items-center gap-1.5 text-[10px] font-mono text-red-400 hover:text-red-300 transition-colors"
      >
        <AlertCircle size={10} />
        AI Offline
      </button>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 text-[10px] font-mono text-green-400">
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2 w-2 bg-green-400" />
      </span>
      AI Online
    </span>
  );
}
