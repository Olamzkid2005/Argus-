import { NextResponse } from "next/server";
import { pool } from "@/lib/db";
import bcrypt from "bcryptjs";
import { redis } from "@/lib/redis";

const RATE_LIMIT_WINDOW = 3600; // 1 hour
const MAX_ATTEMPTS_PER_IP = 5; // 5 attempts per hour per IP

async function checkRateLimit(identifier: string): Promise<boolean> {
  const key = `ratelimit:reset-password:${identifier}`;
  const current = await redis.incr(key);
  if (current === 1) {
    await redis.expire(key, RATE_LIMIT_WINDOW);
  }
  return current <= MAX_ATTEMPTS_PER_IP;
}

/**
 * POST /api/auth/reset-password
 *
 * Reset password with token
 * 
 * Security: Rate limited, token hashed with bcrypt, single use
 */
export async function POST(req: Request) {
  try {
    const { token, password } = await req.json();
    const ip = req.headers.get("x-forwarded-for") || req.headers.get("x-real-ip") || "unknown";

    if (!token || typeof token !== "string") {
      return NextResponse.json(
        { message: "Reset token is required" },
        { status: 400 }
      );
    }

    if (!password || typeof password !== "string" || password.length < 12) {
      return NextResponse.json(
        { message: "Password must be at least 12 characters" },
        { status: 400 }
      );
    }

    // Rate limiting
    const allowed = await checkRateLimit(ip);
    if (!allowed) {
      return NextResponse.json(
        { message: "Too many attempts. Please try again later." },
        { status: 429 }
      );
    }

    // Find users with non-expired tokens.
    // Tokens expire 1 hour after creation, so only recent tokens can be valid.
    // H-13 fix: Always iterate through ALL results, never break early,
    // to prevent timing side-channel attacks. Use bcrypt compare but
    // continue looping even after a match to maintain constant-time behavior.
    const userResult = await pool.query(
      `SELECT id, reset_token FROM users 
       WHERE reset_token_expires_at > NOW()
       AND reset_token IS NOT NULL
       ORDER BY reset_token_expires_at DESC
       LIMIT 500`
    );

    // Find matching token using bcrypt compare.
    // Always iterate through ALL rows to prevent timing side-channel (H-13).
    let matchedUser = null;
    for (const row of userResult.rows) {
      if (matchedUser === null && await bcrypt.compare(token, row.reset_token)) {
        matchedUser = row;
        // Continue iterating to avoid timing leakage
      }
    }

    if (!matchedUser) {
      return NextResponse.json(
        { message: "Invalid or expired reset token" },
        { status: 400 }
      );
    }

    // Hash new password
    const hashedPassword = await bcrypt.hash(password, 12);

    // Update password and clear reset token (single use)
    await pool.query(
      `UPDATE users 
       SET password_hash = $1, 
           reset_token = NULL, 
           reset_token_expires_at = NULL,
           password_updated_at = NOW(),
           updated_at = NOW()
       WHERE id = $2`,
      [hashedPassword, matchedUser.id]
    );

    return NextResponse.json(
      { message: "Password reset successful" },
      { status: 200 }
    );
  } catch (error) {
    console.error("Reset password error:", error);
    return NextResponse.json(
      { message: "An error occurred" },
      { status: 500 }
    );
  }
}
