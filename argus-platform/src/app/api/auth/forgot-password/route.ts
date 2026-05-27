import { NextResponse } from "next/server";
import { pool } from "@/lib/db";
import crypto from "crypto";
import bcrypt from "bcryptjs";
import { redis } from "@/lib/redis";
import { sendPasswordResetEmail } from "@/lib/email";

const RATE_LIMIT_WINDOW = 3600; // 1 hour
const MAX_REQUESTS_PER_EMAIL = 3; // 3 attempts per hour per email
const MAX_REQUESTS_PER_IP = 10; // 10 attempts per hour per IP

async function checkRateLimit(identifier: string, maxRequests: number): Promise<boolean> {
  const key = `ratelimit:forgot-password:${identifier}`;
  const current = await redis.incr(key);
  if (current === 1) {
    await redis.expire(key, RATE_LIMIT_WINDOW);
  }
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
    const ip = req.headers.get("x-forwarded-for") || req.headers.get("x-real-ip") || "unknown";

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

    if (userExists) {
      // Rate limiting by email (only if user exists)
      const emailAllowed = await checkRateLimit(email.toLowerCase(), MAX_REQUESTS_PER_EMAIL);
      if (!emailAllowed) {
        return NextResponse.json(
          { message: "Too many requests. Please try again later." },
          { status: 429 }
        );
      }

      const user = userResult.rows[0];

      // Send password reset email FIRST — only store token if delivery succeeds
      const emailResult = await sendPasswordResetEmail(email.toLowerCase(), resetToken);
      if (!emailResult.success) {
        console.error("Failed to send password reset email:", emailResult.error);
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
    }

    // Always return the same response to prevent email enumeration
    return NextResponse.json(
      { message: "If an account exists, a reset email has been sent" },
      { status: 200 }
    );
  } catch (error) {
    console.error("Forgot password error:", error);
    return NextResponse.json(
      { message: "An error occurred" },
      { status: 500 }
    );
  }
}
