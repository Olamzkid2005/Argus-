/**
 * Audit logging for security and compliance
 *
 * Logs important actions to the execution_logs table for tracking and compliance
 */
import { pool } from "@/lib/db";

export type AuditAction =
  | "user_login"
  | "user_logout"
  | "engagement_create"
  | "engagement_approve"
  | "engagement_delete"
  | "finding_view"
  | "finding_verify"
  | "finding_delete"
  | "finding_bulk_update"
  | "api_request"
  | "auth_failure"
  | "rate_limit_exceeded";

export interface AuditLogEntry {
  action: AuditAction;
  userId?: string;
  orgId?: string;
  engagementId?: string;
  targetId?: string;
  metadata?: Record<string, unknown>;
  ipAddress?: string;
  userAgent?: string;
}

export async function logAudit(entry: AuditLogEntry) {
  try {
    await pool.query(
      `INSERT INTO execution_logs 
        (trace_id, engagement_id, log_level, event_type, message, metadata, created_at)
      VALUES ($1, $2, $3, $4, $5, $6, NOW())`,
      [
        entry.metadata?.trace_id || crypto.randomUUID(),
        entry.engagementId || null,
        "INFO",
        entry.action,
        formatAuditMessage(entry),
        JSON.stringify({
          user_id: entry.userId,
          org_id: entry.orgId,
          target_id: entry.targetId,
          ip_address: entry.ipAddress,
          ...entry.metadata,
        }),
      ],
    );
  } catch (error) {
    console.error("Failed to write audit log:", error);
  }
}

function formatAuditMessage(entry: AuditLogEntry): string {
  const actionMessages: Record<AuditAction, string> = {
    user_login: "User logged in",
    user_logout: "User logged out",
    engagement_create: "Engagement created",
    engagement_approve: "Engagement approved",
    engagement_delete: "Engagement deleted",
    finding_view: "Finding viewed",
    finding_verify: "Finding verified",
    finding_delete: "Finding deleted",
    finding_bulk_update: "Bulk findings updated",
    api_request: "API request",
    auth_failure: "Authentication failure",
    rate_limit_exceeded: "Rate limit exceeded",
  };

  return actionMessages[entry.action] || entry.action;
}

/**
 * Log API request with authentication context
 */
export async function logApiAudit(
  req: Request,
  action: AuditAction,
  userId?: string,
  orgId?: string,
  engagementId?: string,
  metadata?: Record<string, unknown>,
) {
  const ipAddress =
    req.headers.get("x-forwarded-for") ||
    req.headers.get("x-real-ip") ||
    "unknown";
  const userAgent = req.headers.get("user-agent") || "unknown";

  await logAudit({
    action,
    userId,
    orgId,
    engagementId,
    ipAddress,
    userAgent,
    metadata,
  });
}

/**
 * Log authentication failure
 */
export async function logAuthFailure(
  email: string,
  reason: string,
  req: Request,
) {
  await logAudit({
    action: "auth_failure",
    metadata: { email, reason },
    ipAddress: req.headers.get("x-forwarded-for") || "unknown",
    userAgent: req.headers.get("user-agent") || "unknown",
  });
}
