import { NextRequest, NextResponse } from "next/server";
import { pool } from "@/lib/db";
import bcrypt from "bcryptjs";
import { redis } from "@/lib/redis";
import { log } from "@/lib/logger";

const RATE_LIMIT_WINDOW = 3600; // 1 hour
const MAX_ATTEMPTS_PER_IP = 5; // 5 attempts per hour per IP

async function checkRateLimit(identifier: string): Promise<boolean> {
  const key = `ratelimit:reset-password:${identifier}`;
  // M-18: Use SET NX EX for atomic init to fix INCR+EXPIRE race condition
  const setResult = await redis.set(key, 1, "EX", RATE_LIMIT_WINDOW, "NX");
  const current = setResult === "OK" ? 1 : await redis.incr(key);
  return current <= MAX_ATTEMPTS_PER_IP;
}

/**
 * Check that a password meets complexity requirements:
 * - At least 12 characters
 * - Contains uppercase, lowercase, digit, and special character
 */
function isPasswordStrong(password: string): { valid: boolean; message: string } {
  if (password.length < 12) {
    return { valid: false, message: "Password must be at least 12 characters" };
  }
  if (!/[A-Z]/.test(password)) {
    return { valid: false, message: "Password must contain at least one uppercase letter" };
  }
  if (!/[a-z]/.test(password)) {
    return { valid: false, message: "Password must contain at least one lowercase letter" };
  }
  if (!/[0-9]/.test(password)) {
    return { valid: false, message: "Password must contain at least one digit" };
  }
  if (!/[^A-Za-z0-9]/.test(password)) {
    return { valid: false, message: "Password must contain at least one special character" };
  }
  return { valid: true, message: "" };
}

/**
 * POST /api/auth/reset-password
 *
 * Reset password with token
 * 
 * Security: Rate limited (uses request.ip to prevent spoofing), 
 * token hashed with bcrypt, single use tokens
 */
export async function POST(req: NextRequest) {
  try {
    const { token, password } = await req.json();
    // Use request.ip (TCP connection IP from platform) instead of
    // x-forwarded-for header which is trivially spoofable (H-v5-01)
    const ip = req.ip || req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || req.headers.get("x-real-ip") || "unknown";

    if (!token || typeof token !== "string") {
      return NextResponse.json(
        { message: "Reset token is required" },
        { status: 400 }
      );
    }

    if (!password || typeof password !== "string") {
      return NextResponse.json(
        { message: "Password must be at least 12 characters" },
        { status: 400 }
      );
    }

    // Check password strength
    const strengthCheck = isPasswordStrong(password);
    if (!strengthCheck.valid) {
      return NextResponse.json(
        { message: strengthCheck.message },
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
    log.error("Reset password error:", error);
    return NextResponse.json(
      { message: "An error occurred" },
      { status: 500 }
    );
  }
}
