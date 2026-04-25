// 2FA verification after initial login
import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { pool } from "@/lib/db";
import { verifyTOTP } from "@/lib/totp";

export async function POST(req: NextRequest) {
  try {
    const session = await getServerSession(authOptions);

    if (!session?.user) {
      return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
    }

    // Get user ID from session
    const userId = (session.user as { id?: string }).id;
    if (!userId) {
      return NextResponse.json({ error: "Invalid session" }, { status: 401 });
    }

    // Check if user has 2FA pending
    const client = await pool.connect();

    try {
      const result = await client.query(
        "SELECT two_factor_enabled, totp_secret FROM users WHERE id = $1",
        [userId],
      );

      if (result.rows.length === 0) {
        return NextResponse.json({ error: "User not found" }, { status: 404 });
      }

      const user = result.rows[0];

      if (!user.two_factor_enabled || !user.totp_secret) {
        return NextResponse.json(
          { error: "2FA not enabled for this user" },
          { status: 400 },
        );
      }

      const body = await req.json();
      const { code } = body;

      if (!code || code.length !== 6 || !/^\d+$/.test(code)) {
        return NextResponse.json(
          { error: "Invalid verification code - must be 6 digits" },
          { status: 400 },
        );
      }

      // Verify the TOTP code using proper algorithm
      const isValid = await verifyTOTP(user.totp_secret, code, 30, 1);

      if (!isValid) {
        return NextResponse.json(
          { error: "Invalid verification code" },
          { status: 401 },
        );
      }

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
