import { Session } from "next-auth";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

const AUTH_QUERY_RETRIES = 1;
const AUTH_RETRY_DELAY_MS = 150;

/** Custom error classes for authorization failures */
export class NotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NotFoundError";
  }
}

export class ForbiddenError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ForbiddenError";
  }
}

export class ServiceUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ServiceUnavailableError";
  }
}

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
 * Check if user can access an engagement.
 * Verifies both org-level access AND role-based permissions.
 */
export async function canAccessEngagement(
  session: Session,
  engagementId: string,
): Promise<boolean> {
  let result: any = null;
  for (let attempt = 0; attempt <= AUTH_QUERY_RETRIES; attempt++) {
    try {
      result = await pool.query(
        `SELECT e.org_id, e.created_by
         FROM engagements e
         WHERE e.id = $1`,
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
    throw new NotFoundError("Engagement does not exist");
  }

  const engagement = result.rows[0];

  // H-v4-12: Role-based access control — verify the user's role allows access
  // Admin role can access all engagements in the org.
  // Other roles can only access engagements they created.
  const userRole = (session.user as { role?: string }).role || "";
  const isAdmin = userRole === "admin";
  const isOwner = engagement.created_by === (session.user as { id?: string }).id;

  return engagement.org_id === session.user.orgId && (isAdmin || isOwner);
}

/**
 * Verify user has access to the engagement or throw an appropriate error.
 */
export async function requireEngagementAccess(
  session: Session,
  engagementId: string,
): Promise<void> {
  let hasAccess = false;
  try {
    hasAccess = await canAccessEngagement(session, engagementId);
  } catch (error) {
    // Use instanceof checks instead of fragile string matching
    if (error instanceof NotFoundError) {
      throw error;
    }
    log.error("Authorization check error:", { error: String(error) });
    throw new ServiceUnavailableError("Authorization service unavailable");
  }

  if (!hasAccess) {
    throw new ForbiddenError("You do not have access to this engagement");
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
