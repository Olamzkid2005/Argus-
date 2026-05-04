// Shared constants for Argus Platform

export type SeverityLevel = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";

export const SEVERITY_COLORS: Record<SeverityLevel, string> = {
  CRITICAL: "#FF4444",
  HIGH: "#FF8800",
  MEDIUM: "#F59E0B",
  LOW: "#10B981",
  INFO: "#6B7280",
};

export const SEVERITY_ORDER: SeverityLevel[] = [
  "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO",
];

export function getSeverityColor(severity: string): string {
  return SEVERITY_COLORS[severity as SeverityLevel] || SEVERITY_COLORS.INFO;
}

export const SEVERITY_BG_CLASSES: Record<SeverityLevel, string> = {
  CRITICAL: "bg-red-500/20 text-red-400",
  HIGH: "bg-orange-500/20 text-orange-400",
  MEDIUM: "bg-yellow-500/20 text-yellow-400",
  LOW: "bg-green-500/20 text-green-400",
  INFO: "bg-gray-500/20 text-gray-400",
};

export function getSeverityBgClass(severity: string): string {
  return SEVERITY_BG_CLASSES[severity as SeverityLevel] || SEVERITY_BG_CLASSES.INFO;
}

// API endpoints
export const API = {
  ENGAGEMENTS: "/api/engagements",
  FINDINGS: "/api/findings",
  DASHBOARD_STATS: "/api/dashboard/stats",
  SYSTEM_HEALTH: "/api/system/health",
} as const;
