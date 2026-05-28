// Email verification after signup (H-06)
// Accepts a verification code sent via email, looks up the user by token hash,
// and marks their email as verified.
import { NextRequest, NextResponse } from "next/server";
import crypto from "crypto";
import { pool } from "@/lib/db";
import { strictRateLimit } from "@/lib/rate-limiter";
import { log } from "@/lib/logger";

const VERIFICATION_TOKEN_VALIDITY_HOURS = 24;

export async function POST(req: NextRequest) {
  // Rate limit to prevent brute-force attacks on verification codes
  const rateLimitResponse = await strictRateLimit(req);
  if (rateLimitResponse) {
    return rateLimitResponse;
  }

  try {
    const body = await req.json();
    const { token } = body;

    if (!token || typeof token !== "string" || token.length < 8 || token.length > 128) {
      return NextResponse.json(
        { error: "Invalid verification code" },
        { status: 400 },
      );
    }

    // Hash the token to match what's stored in the database
    const tokenHash = crypto.createHash("sha256").update(token).digest("hex");

    const client = await pool.connect();
    try {
      // Find user by verification token hash and check expiry
      const result = await client.query(
        `SELECT id, email, email_verified
         FROM users
         WHERE email_verification_token = $1
           AND email_verification_token_expires > NOW()`,
        [tokenHash],
      );

      if (result.rows.length === 0) {
        // Check if token is expired but user exists (for a better error message)
        const expiredResult = await client.query(
          `SELECT id, email, email_verified
           FROM users
           WHERE email_verification_token = $1`,
          [tokenHash],
        );

        if (expiredResult.rows.length > 0) {
          return NextResponse.json(
            { error: "Verification code has expired. Please request a new one." },
            { status: 410 },
          );
        }

        return NextResponse.json(
          { error: "Invalid verification code" },
          { status: 400 },
        );
      }

      const user = result.rows[0];

      if (user.email_verified) {
        return NextResponse.json(
          { message: "Email already verified" },
          { status: 200 },
        );
      }

      // Mark email as verified and clear the token
      await client.query(
        `UPDATE users
         SET email_verified = true,
             email_verification_token = NULL,
             email_verification_token_expires = NULL
         WHERE id = $1`,
        [user.id],
      );

      log.info("Email verified successfully", { userId: user.id, email: user.email });

      return NextResponse.json({
        success: true,
        message: "Email verified successfully. You can now log in.",
      });
    } finally {
      client.release();
    }
  } catch (error) {
    log.error("Email verification error:", error);
    return NextResponse.json(
      { error: "Failed to verify email. Please try again." },
      { status: 500 },
    );
  }
}
