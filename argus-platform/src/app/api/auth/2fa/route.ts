// 2FA setup endpoint
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";
import { generateSecret, generateOtpAuthUrl, verifyTOTP } from "@/lib/totp";

// Import requireAuth type
type AuthUser = {
  id: string;
  email?: string | null;
  name?: string | null;
  role?: string;
  orgId?: string;
};

export async function POST(req: NextRequest) {
  try {
    const session = await requireAuth();
    const { action } = await req.json();

    const client = await pool.connect();

    try {
      if (action === "setup") {
        // Generate new 2FA secret (20 characters for proper entropy)
        const secret = generateSecret(20);

        // Store temporary secret (not enabled until verified)
        await client.query(
          `
          UPDATE users 
          SET two_factor_secret = $1,
              two_factor_enabled = false,
              updated_at = NOW()
          WHERE id = $2
        `,
          [secret, (session.user as AuthUser).id],
        );

        const userEmail = (session.user as AuthUser).email || 'user@example.com';
        const qrUrl = generateOtpAuthUrl(secret, userEmail, 'Argus');

        return NextResponse.json({
          secret,
          qrUrl,
          message: "Scan the QR code with your authenticator app, then verify",
        });
      }

      if (action === "verify") {
        const { code } = await req.json();

        if (!code || code.length !== 6) {
          return NextResponse.json(
            { error: "Invalid verification code - must be 6 digits" },
            { status: 400 },
          );
        }

        // Get stored secret
        const result = await client.query(
          "SELECT two_factor_secret FROM users WHERE id = $1",
          [(session.user as AuthUser).id],
        );

        const secret = result.rows[0]?.two_factor_secret;

        if (!secret) {
          return NextResponse.json(
            { error: "No 2FA setup in progress" },
            { status: 400 },
          );
        }

        // Verify the TOTP code using proper algorithm
        const isValid = await verifyTOTP(secret, code, 30, 1);

        if (isValid) {
          await client.query(
            `
            UPDATE users 
            SET two_factor_enabled = true,
                updated_at = NOW()
            WHERE id = $1
          `,
            [(session.user as AuthUser).id],
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
          [(session.user as AuthUser).id],
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
