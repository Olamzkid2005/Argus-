// Shared API types for Argus Platform
export interface Finding {
  id: string;
  engagement_id: string;
  type: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
  endpoint: string;
  source_tool: string;
  confidence: number;
  evidence?: Record<string, unknown>;
  created_at: string;
  description?: string;
  remediation?: string;
  cvss_score?: number;
  fp_likelihood?: number;
  tool_agreement_level?: number;
  verification?: Record<string, unknown>;
}

export interface Engagement {
  id: string;
  target_url: string;
  status: string;
  scan_type: string;
  created_at: string;
  updated_at?: string;
  completed_at?: string;
  created_by_email?: string;
  findings_count?: number;
  critical_count?: number;
  max_cycles?: number;
  current_cycles?: number;
}

export type EngagementStatus =
  | "created" | "recon" | "scanning" | "analyzing"
  | "reporting" | "complete" | "failed" | "cancelled";

export interface EngagementState {
  id: string;
  engagement_id: string;
  from_state: string | null;
  to_state: string;
  reason: string;
  created_at: string;
}

export interface ToolMetric {
  tool_name: string;
  success_count: number;
  failure_count: number;
  avg_duration_ms: number;
  last_run?: string;
  is_healthy: boolean;
}

export interface TimelineEvent {
  id: string;
  engagement_id: string;
  event_type: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface ScanActivity {
  tool_name: string;
  status: "running" | "completed" | "failed";
  message?: string;
  started_at: string;
  completed_at?: string;
  findings_count?: number;
}

export interface PaginatedResponse<T> {
  data: T[];
  meta: {
    total: number;
    page: number;
    limit: number;
    totalPages: number;
  };
}
