import { getServerSession } from "next-auth";
import { authOptions } from "./auth";
import { NextResponse } from "next/server";
import redis from "./redis";

const SESSION_TTL = 30 * 24 * 60 * 60; // 30 days

export async function getSession() {
  return await getServerSession(authOptions);
}

export async function requireAuth() {
  const session = await getSession();

  if (!session || !session.user) {
    throw new Error("Unauthorized");
  }

  return session;
}

export function withAuth(
  handler: (
    req: Request,
    context?: Record<string, unknown>,
    session?: Awaited<ReturnType<typeof requireAuth>>,
  ) => Promise<NextResponse | Response>,
) {
  return async (req: Request, context?: Record<string, unknown>) => {
    try {
      const session = await requireAuth();
      return await handler(req, context, session);
    } catch {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
  };
}

/**
 * Store session in Redis for horizontal scaling support.
 * Multiple Next.js instances can share sessions via Redis.
 */
export async function storeSessionInRedis(
  sessionId: string,
  sessionData: Record<string, unknown>
): Promise<void> {
  try {
    await redis.setex(
      `session:${sessionId}`,
      SESSION_TTL,
      JSON.stringify(sessionData)
    );
  } catch (error) {
    console.error("Failed to store session in Redis:", error);
  }
}

/**
 * Retrieve session from Redis
 */
export async function getSessionFromRedis(
  sessionId: string
): Promise<Record<string, unknown> | null> {
  try {
    const data = await redis.get(`session:${sessionId}`);
    if (!data) return null;
    return JSON.parse(data);
  } catch (error) {
    console.error("Failed to get session from Redis:", error);
    return null;
  }
}

/**
 * Destroy session in Redis
 */
export async function destroySessionInRedis(sessionId: string): Promise<void> {
  try {
    await redis.del(`session:${sessionId}`);
  } catch (error) {
    console.error("Failed to destroy session in Redis:", error);
  }
}
