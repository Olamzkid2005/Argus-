import { useState, useEffect, useMemo } from "react";

export interface ScanEstimateConfig {
  targetType?: "web" | "api" | "network" | "default";
  aggressiveness?: "low" | "medium" | "high";
}

export interface PhaseEstimate {
  id: string;
  label: string;
  estimatedMinutes: number;
  estimatedMs: number;
}

function formatDuration(ms: number): string {
  if (ms <= 0) return "—";
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

export function formatShortDuration(minutes: number): string {
  if (minutes < 1) return "< 1m";
  return `~${Math.round(minutes)}m`;
}

const BASE_ESTIMATES: Record<string, { min: number; max: number }> = {
  recon: { min: 2, max: 5 },
  fingerprinting: { min: 3, max: 8 },
  vuln_mapping: { min: 5, max: 15 },
  reporting: { min: 1, max: 2 },
};

const TARGET_MULTIPLIERS: Record<string, number> = {
  web: 1.0,
  api: 0.9,
  network: 1.2,
  default: 1.0,
};

const AGGRESSIVENESS_MULTIPLIERS: Record<string, number> = {
  low: 0.8,
  medium: 1.0,
  high: 1.3,
};

const STATE_ORDER = ["created", "recon", "scanning", "analyzing", "reporting", "complete"];

function getPhaseLabel(id: string): string {
  switch (id) {
    case "recon":
      return "Reconnaissance";
    case "fingerprinting":
      return "Fingerprinting";
    case "vuln_mapping":
      return "Vulnerability Mapping";
    case "reporting":
      return "Final Reporting";
    default:
      return id;
  }
}

function getStepStatus(stepId: string, currentState: string): "pending" | "in_progress" | "completed" {
  const currentIdx = STATE_ORDER.indexOf(currentState);

  if (stepId === "recon") {
    if (currentState === "recon") return "in_progress";
    if (currentIdx > STATE_ORDER.indexOf("recon")) return "completed";
  }
  if (stepId === "fingerprinting") {
    if (currentState === "scanning") return "in_progress";
    if (currentIdx > STATE_ORDER.indexOf("scanning")) return "completed";
  }
  if (stepId === "vuln_mapping") {
    if (currentState === "analyzing") return "in_progress";
    if (currentIdx > STATE_ORDER.indexOf("analyzing")) return "completed";
  }
  if (stepId === "reporting") {
    if (currentState === "reporting") return "in_progress";
    if (currentState === "complete") return "completed";
  }
  return "pending";
}

export function useScanEstimates(
  currentState: string,
  config: ScanEstimateConfig = {},
  startTime?: string | Date | null
) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const { targetType = "default", aggressiveness = "medium" } = config;

  const phaseEstimates = useMemo(() => {
    const targetMult = TARGET_MULTIPLIERS[targetType] ?? 1.0;
    const aggMult = AGGRESSIVENESS_MULTIPLIERS[aggressiveness] ?? 1.0;

    return Object.entries(BASE_ESTIMATES).map(([id, { min, max }]) => {
      const estimatedMinutes = Math.round(((min + max) / 2) * targetMult * aggMult);
      return {
        id,
        label: getPhaseLabel(id),
        estimatedMinutes,
        estimatedMs: estimatedMinutes * 60 * 1000,
      };
    });
  }, [targetType, aggressiveness]);

  const totalEstimatedMinutes = useMemo(
    () => phaseEstimates.reduce((sum, p) => sum + p.estimatedMinutes, 0),
    [phaseEstimates]
  );

  const startTimestamp = useMemo(() => {
    if (!startTime) return null;
    return new Date(startTime).getTime();
  }, [startTime]);

  const elapsedMs = useMemo(() => {
    if (!startTimestamp) return 0;
    return Math.max(0, now - startTimestamp);
  }, [startTimestamp, now]);

  const elapsedFormatted = useMemo(() => formatDuration(elapsedMs), [elapsedMs]);

  const currentPhase = useMemo(() => {
    return phaseEstimates.find((p) => getStepStatus(p.id, currentState) === "in_progress") || null;
  }, [phaseEstimates, currentState]);

  const getPhaseStatus = (stepId: string): "pending" | "in_progress" | "completed" => {
    return getStepStatus(stepId, currentState);
  };

  const getPhaseElapsed = (stepId: string): number => {
    const status = getStepStatus(stepId, currentState);
    if (status === "pending") return 0;

    const phaseIdx = phaseEstimates.findIndex((p) => p.id === stepId);
    let precedingMs = 0;
    for (let i = 0; i < phaseIdx; i++) {
      precedingMs += phaseEstimates[i].estimatedMs;
    }

    if (status === "completed") {
      return phaseEstimates[phaseIdx].estimatedMs;
    }

    const rawElapsed = elapsedMs - precedingMs;
    return Math.max(0, Math.min(rawElapsed, phaseEstimates[phaseIdx].estimatedMs));
  };

  const getPhaseRemaining = (stepId: string): number => {
    const status = getStepStatus(stepId, currentState);
    if (status !== "in_progress") return 0;
    const phase = phaseEstimates.find((p) => p.id === stepId);
    if (!phase) return 0;
    const phaseElapsed = getPhaseElapsed(stepId);
    return Math.max(0, phase.estimatedMs - phaseElapsed);
  };

  const getPhaseProgress = (stepId: string): number => {
    const status = getStepStatus(stepId, currentState);
    const phase = phaseEstimates.find((p) => p.id === stepId);
    if (!phase) return 0;
    if (status === "completed") return 100;
    if (status === "pending") return 0;
    const phaseElapsed = getPhaseElapsed(stepId);
    return Math.min(100, Math.round((phaseElapsed / phase.estimatedMs) * 100));
  };

  const getPhaseCompletionTime = (stepId: string): Date | null => {
    const status = getStepStatus(stepId, currentState);
    if (status !== "completed" || !startTimestamp) return null;
    const phaseIdx = phaseEstimates.findIndex((p) => p.id === stepId);
    let precedingMs = 0;
    for (let i = 0; i <= phaseIdx; i++) {
      precedingMs += phaseEstimates[i].estimatedMs;
    }
    return new Date(startTimestamp + precedingMs);
  };

  const remainingMs = useMemo(() => {
    if (!currentPhase) return 0;
    return getPhaseRemaining(currentPhase.id);
  }, [currentPhase, elapsedMs]);

  const remainingFormatted = useMemo(() => formatDuration(remainingMs), [remainingMs]);

  const phaseHistory = useMemo(() => {
    if (!startTimestamp) return [];
    return phaseEstimates
      .map((phase) => {
        const status = getStepStatus(phase.id, currentState);
        const completionTime = getPhaseCompletionTime(phase.id);
        return {
          ...phase,
          status,
          completionTime,
        };
      })
      .filter((p) => p.status === "completed");
  }, [phaseEstimates, currentState, startTimestamp]);

  return {
    phaseEstimates,
    totalEstimatedMinutes,
    elapsedMs,
    elapsedFormatted,
    remainingMs,
    remainingFormatted,
    currentPhase,
    getPhaseStatus,
    getPhaseElapsed,
    getPhaseRemaining,
    getPhaseProgress,
    getPhaseCompletionTime,
    phaseHistory,
    formatDuration,
  };
}
