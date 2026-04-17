import { Pool } from "pg";
import { Session } from "next-auth";

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

/**
 * Check if user can access an engagement
 */
export async function canAccessEngagement(
  session: Session,
  engagementId: string
): Promise<boolean> {
  try {
    const result = await pool.query(
      "SELECT org_id FROM engagements WHERE id = $1",
      [engagementId]
    );

    if (result.rows.length === 0) {
      return false;
    }

    const engagement = result.rows[0];
    return engagement.org_id === session.user.orgId;
  } catch (error) {
    console.error("Authorization check error:", error);
    return false;
  }
}

/**
 * Verify user owns the engagement or throw error
 */
export async function requireEngagementAccess(
  session: Session,
  engagementId: string
): Promise<void> {
  const hasAccess = await canAccessEngagement(session, engagementId);
  
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
