import { getServerSession } from "next-auth";
import { authOptions } from "./auth";
import { NextResponse } from "next/server";

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

export function withAuth(handler: (req: Request, context?: Record<string, unknown>, session?: Awaited<ReturnType<typeof requireAuth>>) => Promise<NextResponse | Response>) {
  return async (req: Request, context?: Record<string, unknown>) => {
    try {
      const session = await requireAuth();
      return await handler(req, context, session);
    } catch {
      return NextResponse.json(
        { error: "Unauthorized" },
        { status: 401 }
      );
    }
  };
}
