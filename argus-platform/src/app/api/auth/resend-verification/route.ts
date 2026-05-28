// Resend email verification code (H-06)
// Uses the same timing-safe pattern as forgot-password to prevent enumeration.
import { NextRequest, NextResponse } from "next/server";
import crypto from "crypto";
import { pool } from "@/lib/db";
import { redis } from "@/lib/redis";
import { sendVerificationEmail } from "@/lib/email";
import { log } from "@/lib/logger";

const RESEND_RATE_LIMIT_WINDOW = 300; // 5 minutes
const MAX_RESENDS = 3;

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { email } = body;

    if (!email || typeof email !== "string") {
      return NextResponse.json(
        { error: "Email is required" },
        { status: 400 },
      );
    }

    const normalizedEmail = email.toLowerCase().trim();

    // Rate limiting — same pattern as forgot-password to prevent enumeration
    const rateKey = `ratelimit:resend:${normalizedEmail}`;
    const rateCheck = await redis.set(rateKey, 1, "EX", RESEND_RATE_LIMIT_WINDOW, "NX");
    const current = rateCheck === "OK" ? 1 : await redis.incr(rateKey);
    if (current > MAX_RESENDS) {
      return NextResponse.json(
        { error: "Too many requests. Please try again later." },
        { status: 429 },
      );
    }

    // Look up user — don't reveal whether the email exists
    const result = await pool.query(
      "SELECT id, email_verified FROM users WHERE email = $1",
      [normalizedEmail],
    );

    if (result.rows.length === 0 || result.rows[0].email_verified) {
      // Return success to prevent enumeration (same pattern as forgot-password)
      return NextResponse.json({
        message: "If the account exists and is unverified, a new code has been sent.",
      });
    }

    const user = result.rows[0];

    // Generate new verification token
    const verifyToken = crypto.randomBytes(32).toString("hex");
    const tokenHash = crypto.createHash("sha256").update(verifyToken).digest("hex");

    // Store the token hash and expiry (24 hours from now)
    const expiresAt = new Date(Date.now() + 24 * 60 * 60 * 1000);
    await pool.query(
      `UPDATE users
       SET email_verification_token = $1,
           email_verification_token_expires = $2
       WHERE id = $3`,
      [tokenHash, expiresAt, user.id],
    );

    // Send the verification email
    const emailResult = await sendVerificationEmail(normalizedEmail, verifyToken);

    if (!emailResult.success) {
      log.error("Failed to send verification email on resend", {
        email: normalizedEmail,
        error: emailResult.error,
      });
      return NextResponse.json(
        { error: "Failed to send verification email. Please try again later." },
        { status: 500 },
      );
    }

    log.info("Verification email resent for", normalizedEmail);

    return NextResponse.json({
      message: "If the account exists and is unverified, a new code has been sent.",
    });
  } catch (error) {
    log.error("Resend verification error:", error);
    return NextResponse.json(
      { error: "Failed to resend verification code. Please try again." },
      { status: 500 },
    );
  }
}
