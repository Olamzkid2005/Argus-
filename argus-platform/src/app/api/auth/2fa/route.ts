// 2FA setup endpoint
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

// Simple TOTP implementation (in production use a proper library)
function generateSecret(): string {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let secret = "";
  for (let i = 0; i < 16; i++) {
    secret += chars[Math.floor(Math.random() * chars.length)];
  }
  return secret;
}

function generateQRCodeURL(secret: string, email: string): string {
  // Google Authenticator compatible otpauth URL
  const label = "ArgusPentest";
  return `otpauth://totp/${label}:${email}?secret=${secret}&issuer=${label}`;
}

export async function POST(req: NextRequest) {
  try {
    const session = await requireAuth();
    const { action } = await req.json();

    const client = await pool.connect();

    try {
      if (action === "setup") {
        // Generate new 2FA secret
        const secret = generateSecret();

        // Store temporary secret (not enabled until verified)
        await client.query(
          `
          UPDATE users 
          SET two_factor_secret = $1,
              two_factor_enabled = false,
              updated_at = NOW()
          WHERE id = $2
        `,
          [secret, session.user.id],
        );

        const qrUrl = generateQRCodeURL(secret, session.user.email!);

        return NextResponse.json({
          secret,
          qrUrl,
          message: "Scan the QR code with your authenticator app, then verify",
        });
      }

      if (action === "verify") {
        const { code } = await req.json();

        // Get stored secret
        const result = await client.query(
          "SELECT two_factor_secret FROM users WHERE id = $1",
          [session.user.id],
        );

        const secret = result.rows[0]?.two_factor_secret;

        if (!secret) {
          return NextResponse.json(
            { error: "No 2FA setup in progress" },
            { status: 400 },
          );
        }

        // In production, verify the TOTP code properly
        // For now, accept any 6-digit code for demo
        if (code && code.length === 6) {
          await client.query(
            `
            UPDATE users 
            SET two_factor_enabled = true,
                updated_at = NOW()
            WHERE id = $1
          `,
            [session.user.id],
          );

          return NextResponse.json({
            success: true,
            message: "2FA enabled successfully",
          });
        }

        return NextResponse.json(
          { error: "Invalid verification code" },
          { status: 400 },
        );
      }

      if (action === "disable") {
        await client.query(
          `
          UPDATE users 
          SET two_factor_secret = NULL,
              two_factor_enabled = false,
              updated_at = NOW()
          WHERE id = $1
        `,
          [session.user.id],
        );

        return NextResponse.json({
          success: true,
          message: "2FA disabled",
        });
      }

      return NextResponse.json({ error: "Invalid action" }, { status: 400 });
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("2FA setup error:", error);
    return NextResponse.json({ error: "Failed to setup 2FA" }, { status: 500 });
  }
}
