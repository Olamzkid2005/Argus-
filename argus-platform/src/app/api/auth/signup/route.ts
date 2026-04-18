import { NextRequest, NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { v4 as uuidv4 } from "uuid";
import { pool } from "@/lib/db";

// Validation functions
function isValidEmail(email: string): boolean {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
}

function isValidPassword(password: string): { valid: boolean; message?: string } {
  if (password.length < 8) {
    return { valid: false, message: "Password must be at least 8 characters long" };
  }
  if (password.length > 128) {
    return { valid: false, message: "Password must be at most 128 characters long" };
  }
  if (!/[A-Z]/.test(password)) {
    return { valid: false, message: "Password must contain at least one uppercase letter" };
  }
  if (!/[a-z]/.test(password)) {
    return { valid: false, message: "Password must contain at least one lowercase letter" };
  }
  if (!/[0-9]/.test(password)) {
    return { valid: false, message: "Password must contain at least one number" };
  }
  return { valid: true };
}

function isValidOrgName(name: string): boolean {
  return name.trim().length >= 2 && name.trim().length <= 255;
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { email, password, passwordConfirm, orgName } = body;

    // Validate required fields
    if (!email || !password || !passwordConfirm || !orgName) {
      return NextResponse.json(
        { error: "All fields are required" },
        { status: 400 }
      );
    }

    // Validate email format
    if (!isValidEmail(email)) {
      return NextResponse.json(
        { error: "Invalid email format" },
        { status: 400 }
      );
    }

    // Validate password
    const passwordValidation = isValidPassword(password);
    if (!passwordValidation.valid) {
      return NextResponse.json(
        { error: passwordValidation.message },
        { status: 400 }
      );
    }

    // Validate password confirmation
    if (password !== passwordConfirm) {
      return NextResponse.json(
        { error: "Passwords do not match" },
        { status: 400 }
      );
    }

    // Validate organization name
    if (!isValidOrgName(orgName)) {
      return NextResponse.json(
        { error: "Organization name must be between 2 and 255 characters" },
        { status: 400 }
      );
    }

    // Check if user already exists
    const existingUser = await pool.query(
      "SELECT id FROM users WHERE email = $1",
      [email.toLowerCase().trim()]
    );

    if (existingUser.rows.length > 0) {
      // Generic error message to prevent email enumeration
      return NextResponse.json(
        { error: "Account creation failed. Please try again." },
        { status: 409 }
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
        [orgId, orgName.trim()]
      );

      // Create user with admin role (first user of the org)
      const userId = uuidv4();
      await client.query(
        `INSERT INTO users (id, org_id, email, password_hash, role)
         VALUES ($1, $2, $3, $4, $5)`,
        [userId, orgId, email.toLowerCase().trim(), passwordHash, "admin"]
      );

      await client.query("COMMIT");

      return NextResponse.json(
        {
          message: "Account created successfully",
          user: { id: userId, email: email.toLowerCase().trim() },
        },
        { status: 201 }
      );
    } catch (txError) {
      await client.query("ROLLBACK");
      throw txError;
    } finally {
      client.release();
    }
  } catch (error) {
    console.error("Signup error:", error);
    return NextResponse.json(
      { error: "An error occurred during sign up. Please try again." },
      { status: 500 }
    );
  }
}