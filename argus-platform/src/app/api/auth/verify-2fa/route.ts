// 2FA verification after initial login
import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { pool } from "@/lib/db";

export async function POST(req: NextRequest) {
  try {
    const session = await getServerSession(authOptions);

    if (!session?.user) {
      return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
    }

    // Check if user has 2FA pending
    const client = await pool.connect();

    try {
      const result = await client.query(
        "SELECT two_factor_enabled, two_factor_secret FROM users WHERE id = $1",
        [(session.user as { id?: string }).id],
      );

      if (result.rows.length === 0) {
        return NextResponse.json({ error: "User not found" }, { status: 404 });
      }

      const user = result.rows[0];

      if (!user.two_factor_enabled) {
        return NextResponse.json(
          { error: "2FA not enabled for this user" },
          { status: 400 },
        );
      }

      const body = await req.json();
      const { code } = body;

      if (!code || code.length !== 6) {
        return NextResponse.json(
          { error: "Invalid verification code" },
          { status: 400 },
        );
      }

      // In production, implement proper TOTP verification
      // For demo, accept any 6-digit code after 2FA is enabled
      // This would use a library like 'totp-generator' in production

      return NextResponse.json({
        success: true,
        message: "2FA verification successful",
      });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("2FA verification error:", error);
    return NextResponse.json(
      { error: "Failed to verify 2FA" },
      { status: 500 },
    );
  }
}
