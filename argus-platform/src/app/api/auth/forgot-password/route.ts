import { NextRequest, NextResponse } from "next/server";
import { pool } from "@/lib/db";
import crypto from "crypto";
import bcrypt from "bcryptjs";
import { redis } from "@/lib/redis";
import { sendPasswordResetEmail } from "@/lib/email";
import { log } from "@/lib/logger";

const RATE_LIMIT_WINDOW = 3600; // 1 hour
const MAX_REQUESTS_PER_EMAIL = 3; // 3 attempts per hour per email
const MAX_REQUESTS_PER_IP = 10; // 10 attempts per hour per IP

async function checkRateLimit(identifier: string, maxRequests: number): Promise<boolean> {
  const key = `ratelimit:forgot-password:${identifier}`;
  // M-18: Use SET NX EX for atomic init to fix INCR+EXPIRE race condition.
  // SET NX only succeeds if key doesn't exist, atomically setting count=1 with TTL.
  const setResult = await redis.set(key, 1, "EX", RATE_LIMIT_WINDOW, "NX");
  const current = setResult === "OK" ? 1 : await redis.incr(key);
  return current <= maxRequests;
}

/**
 * POST /api/auth/forgot-password
 *
 * Request password reset email
 * 
 * Security: Rate limited, tokens hashed, no email enumeration
 */
export async function POST(req: Request) {
  try {
    const { email } = await req.json();
    // Cast to NextRequest to access .ip (TCP connection IP from platform)
    // instead of using x-forwarded-for header which is trivially spoofable (H-v5-01)
    const nextReq = req as NextRequest;
    const ip = nextReq.ip || req.headers.get("x-forwarded-for") || req.headers.get("x-real-ip") || "unknown";

    if (!email || typeof email !== "string") {
      return NextResponse.json(
        { message: "Email is required" },
        { status: 400 }
      );
    }

    // Rate limiting by IP
    const ipAllowed = await checkRateLimit(ip, MAX_REQUESTS_PER_IP);
    if (!ipAllowed) {
      return NextResponse.json(
        { message: "Too many requests. Please try again later." },
        { status: 429 }
      );
    }

    // Generate a reset token regardless of whether user exists
    // to prevent timing-based email enumeration (H-v3-07)
    const resetToken = crypto.randomBytes(32).toString("hex");
    const hashedToken = await bcrypt.hash(resetToken, 12);
    const resetTokenExpiry = new Date(Date.now() + 3600000); // 1 hour from now

    // Check if user exists
    const userResult = await pool.query(
      "SELECT id, name FROM users WHERE email = $1",
      [email.toLowerCase()]
    );

    const userExists = userResult.rows.length > 0;

    // M-20: Always apply email rate limiting regardless of user existence to
    // prevent timing-based email enumeration. For non-existing users, we use a
    // synthetic key so the rate limit check takes the same duration.
    const rateLimitKey = userExists ? email.toLowerCase() : `nonexistent:${email.toLowerCase()}`;
    const emailAllowed = await checkRateLimit(rateLimitKey, MAX_REQUESTS_PER_EMAIL);
    if (!emailAllowed) {
      return NextResponse.json(
        { message: "Too many requests. Please try again later." },
        { status: 429 }
      );
    }

    if (userExists) {
      const user = userResult.rows[0];

      // Send password reset email FIRST — only store token if delivery succeeds
      const emailResult = await sendPasswordResetEmail(email.toLowerCase(), resetToken);
      if (!emailResult.success) {
        log.error("Failed to send password reset email:", emailResult.error);
        return NextResponse.json(
          { message: "Unable to send reset email. Please try again later." },
          { status: 500 }
        );
      }

      // Store hashed token in database ONLY after email sent successfully
      await pool.query(
        `UPDATE users 
         SET reset_token = $1, reset_token_expires_at = $2 
         WHERE id = $3`,
        [hashedToken, resetTokenExpiry, user.id]
      );
    } else {
      // M-20: Simulate the same operations for non-existing users to prevent
      // timing-based enumeration. The bcrypt hash and token generation already
      // ran above, and we add a small artificial delay to match email send time.
      await new Promise(resolve => setTimeout(resolve, 100));
    }

    // Always return the same response to prevent email enumeration
    return NextResponse.json(
      { message: "If an account exists, a reset email has been sent" },
      { status: 200 }
    );
  } catch (error) {
    log.error("Forgot password error:", error);
    return NextResponse.json(
      { message: "An error occurred" },
      { status: 500 }
    );
  }
}
