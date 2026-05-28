import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { v4 as uuidv4 } from "uuid";
import { pool } from "@/lib/db";
import { redis } from "@/lib/redis";
import { log } from "@/lib/logger";
// M-12: Use Zod schema instead of inline validation
import { signupSchema } from "@/lib/validation/consolidated";

const RATE_LIMIT_WINDOW = 3600; // 1 hour
const MAX_SIGNUPS_PER_EMAIL = 5; // 5 attempts per hour per email
const MAX_SIGNUPS_PER_IP = 10; // 10 attempts per hour per IP

async function checkRateLimit(identifier: string, maxRequests: number): Promise<boolean> {
  const key = `ratelimit:signup:${identifier}`;
  // M-18: Use SET NX EX for atomic init to fix INCR+EXPIRE race condition
  const setResult = await redis.set(key, 1, "EX", RATE_LIMIT_WINDOW, "NX");
  const current = setResult === "OK" ? 1 : await redis.incr(key);
  return current <= maxRequests;
}

// M-12: Validation now handled by signupSchema (Zod) — inline functions removed

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { email, password, passwordConfirm, orgName } = body;

    // Use request.ip (TCP connection IP from platform) instead of
    // x-forwarded-for header which is trivially spoofable (H-v5-01)
    const ip = request.ip || request.headers.get("x-forwarded-for") || request.headers.get("x-real-ip") || "unknown";

    const ipAllowed = await checkRateLimit(ip, MAX_SIGNUPS_PER_IP);
    if (!ipAllowed) {
      return NextResponse.json(
        { error: "Too many requests. Please try again later." },
        { status: 429 },
      );
    }

    // M-12: Use Zod schema for validation instead of inline checks
    const validation = signupSchema.safeParse({ email, password, passwordConfirm, orgName });
    if (!validation.success) {
      const firstError = validation.error.errors[0];
      return NextResponse.json(
        { error: firstError?.message || "Invalid input" },
        { status: 400 },
      );
    }

    // Check if user already exists
    const existingUser = await pool.query(
      "SELECT id FROM users WHERE email = $1",
      [email.toLowerCase().trim()],
    );

    if (existingUser.rows.length > 0) {
      // Generic error message to prevent email enumeration
      return NextResponse.json(
        { error: "Account creation failed. Please try again." },
        { status: 409 },
      );
    }

    // Rate limiting by email
    const emailAllowed = await checkRateLimit(email.toLowerCase().trim(), MAX_SIGNUPS_PER_EMAIL);
    if (!emailAllowed) {
      return NextResponse.json(
        { error: "Too many requests. Please try again later." },
        { status: 429 },
      );
    }

    // Hash password
    const saltRounds = 12;
    const passwordHash = await bcrypt.hash(password, saltRounds);

    // Create organization and user in a transaction
    const client = await pool.connect();
    try {
      await client.query("BEGIN");

      // Create organization
      const orgId = uuidv4();
      await client.query(
        "INSERT INTO organizations (id, name) VALUES ($1, $2)",
        [orgId, orgName.trim()],
      );

      // Create user with admin role (first user of the org)
      const userId = uuidv4();
      await client.query(
        `INSERT INTO users (id, org_id, email, password_hash, role)
         VALUES ($1, $2, $3, $4, $5)`,
        [userId, orgId, email.toLowerCase().trim(), passwordHash, "admin"],
      );

      await client.query("COMMIT");

      return NextResponse.json(
        {
          message: "Account created successfully",
          user: { id: userId, email: email.toLowerCase().trim() },
        },
        { status: 201 },
      );
    } catch (txError) {
      await client.query("ROLLBACK");
      throw txError;
    } finally {
      client.release();
    }
  } catch (error) {
    log.error("Signup error:", error);
    return NextResponse.json(
      { error: "An error occurred during sign up. Please try again." },
      { status: 500 },
    );
  }
}
