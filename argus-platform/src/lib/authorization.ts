import { Session } from "next-auth";
import { pool } from "@/lib/db";

const AUTH_QUERY_RETRIES = 1;
const AUTH_RETRY_DELAY_MS = 150;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isTransientDbError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  const message = error.message.toLowerCase();
  return (
    message.includes("connection terminated") ||
    message.includes("connection timeout") ||
    message.includes("connection ended unexpectedly") ||
    message.includes("terminating connection") ||
    message.includes("econnreset")
  );
}

/**
 * Check if user can access an engagement
 */
export async function canAccessEngagement(
  session: Session,
  engagementId: string,
): Promise<boolean> {
  let result: any = null;
  for (let attempt = 0; attempt <= AUTH_QUERY_RETRIES; attempt++) {
    try {
      result = await pool.query(
        "SELECT org_id FROM engagements WHERE id = $1",
        [engagementId],
      );
      break;
    } catch (error) {
      const canRetry =
        attempt < AUTH_QUERY_RETRIES && isTransientDbError(error);
      if (!canRetry) {
        throw error;
      }
      await delay(AUTH_RETRY_DELAY_MS * (attempt + 1));
    }
  }

  if (!result || result.rows.length === 0) {
    throw new Error("NotFound: Engagement does not exist");
  }

  const engagement = result.rows[0];
  return engagement.org_id === session.user.orgId;
}

/**
 * Verify user owns the engagement or throw error
 */
export async function requireEngagementAccess(
  session: Session,
  engagementId: string,
): Promise<void> {
  let hasAccess = false;
  try {
    hasAccess = await canAccessEngagement(session, engagementId);
  } catch (error) {
    // Let NotFound errors propagate through (they're not service failures)
    if (error instanceof Error && error.message.startsWith("NotFound")) {
      throw error;
    }
    console.error("Authorization check error:", error);
    throw new Error("ServiceUnavailable: Authorization service unavailable");
  }

  if (!hasAccess) {
    throw new Error("Forbidden: You do not have access to this engagement");
  }
}

/**
 * Filter query results by organization
 */
export function filterByOrganization(orgId: string) {
  return {
    where: { org_id: orgId },
  };
}
