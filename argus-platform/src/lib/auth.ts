import { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import GoogleProvider from "next-auth/providers/google";
import GitHubProvider from "next-auth/providers/github";
import bcrypt from "bcryptjs";
import { v4 as uuidv4 } from "uuid";
import { pool } from "@/lib/db";

// Security configuration
const MAX_LOGIN_ATTEMPTS = 5;
const LOCKOUT_DURATION_MINUTES = 15;
const SESSION_MAX_AGE = 24 * 60 * 60; // 24 hours

/**
 * Check if account is locked out due to failed login attempts
 */
async function checkAccountLockout(
  email: string,
): Promise<{ locked: boolean; reason?: string }> {
  try {
    const result = await pool.query(
      `SELECT locked_until, failed_login_attempts 
       FROM users WHERE email = $1`,
      [email.toLowerCase()],
    );

    if (result.rows.length === 0) {
      return { locked: false };
    }

    const user = result.rows[0];

    // Check if account is currently locked
    if (user.locked_until && new Date(user.locked_until) > new Date()) {
      const lockedUntil = new Date(user.locked_until);
      const minutesLeft = Math.ceil(
        (lockedUntil.getTime() - Date.now()) / 60000,
      );
      return {
        locked: true,
        reason: `Account locked. Try again in ${minutesLeft} minute(s).`,
      };
    }

    // Check if max attempts reached
    if (user.failed_login_attempts >= MAX_LOGIN_ATTEMPTS) {
      const lockoutUntil = new Date(
        Date.now() + LOCKOUT_DURATION_MINUTES * 60 * 1000,
      );
      await pool.query(
        `UPDATE users SET locked_until = $1, failed_login_attempts = 0 
         WHERE email = $2`,
        [lockoutUntil, email.toLowerCase()],
      );
      return {
        locked: true,
        reason: `Too many failed attempts. Account locked for ${LOCKOUT_DURATION_MINUTES} minutes.`,
      };
    }

    return { locked: false };
  } catch (error) {
    console.error("Lockout check error:", error);
    // Fail open - don't block login if check fails
    return { locked: false };
  }
}

/**
 * Record failed login attempt and update lockout if needed
 */
async function recordFailedLoginAttempt(email: string): Promise<void> {
  try {
    const result = await pool.query(
      `SELECT failed_login_attempts FROM users WHERE email = $1`,
      [email.toLowerCase()],
    );

    if (result.rows.length > 0) {
      const attempts = (result.rows[0].failed_login_attempts || 0) + 1;

      // If max attempts reached, lock the account
      if (attempts >= MAX_LOGIN_ATTEMPTS) {
        const lockoutUntil = new Date(
          Date.now() + LOCKOUT_DURATION_MINUTES * 60 * 1000,
        );
        await pool.query(
          `UPDATE users SET failed_login_attempts = $1, locked_until = $2 
           WHERE email = $3`,
          [attempts, lockoutUntil, email.toLowerCase()],
        );
      } else {
        await pool.query(
          `UPDATE users SET failed_login_attempts = $1 WHERE email = $2`,
          [attempts, email.toLowerCase()],
        );
      }
    }
  } catch (error) {
    console.error("Failed to record login attempt:", error);
  }
}

/**
 * Clear failed login attempts on successful login
 */
async function clearFailedLoginAttempts(email: string): Promise<void> {
  try {
    await pool.query(
      `UPDATE users SET failed_login_attempts = 0, locked_until = NULL, last_login_at = NOW() 
       WHERE email = $1`,
      [email.toLowerCase()],
    );
  } catch (error) {
    console.error("Failed to clear login attempts:", error);
  }
}

interface User {
  id: string;
  email: string;
  orgId: string;
  role: string;
}

interface JWTtoken {
  id?: string;
  orgId?: string;
  role?: string;
}

interface OAuthUser {
  id?: string;
  email?: string | null;
  name?: string | null;
  image?: string | null;
  orgId?: string;
  role?: string;
}

export const authOptions: NextAuthOptions = {
  providers: [
    GoogleProvider({
      clientId: process.env.GOOGLE_CLIENT_ID ?? "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? "",
    }),
    GitHubProvider({
      clientId: process.env.GITHUB_CLIENT_ID ?? "",
      clientSecret: process.env.GITHUB_CLIENT_SECRET ?? "",
    }),
    CredentialsProvider({
      name: "Credentials",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) {
          return null;
        }

        try {
          // Check if account is locked out FIRST (before any auth attempt)
          const lockoutCheck = await checkAccountLockout(credentials.email);
          if (lockoutCheck.locked) {
            // Audit the blocked attempt
            try {
              const { logAuthFailure } = await import("@/lib/audit");
              await logAuthFailure(credentials.email, lockoutCheck.reason || "Account locked", {} as Request);
            } catch {}
            
            // Return error info via throwing (NextAuth will handle this)
            throw new Error("ACCOUNT_LOCKED:" + (lockoutCheck.reason || "Account locked"));
          }

          // Query user from database (now include new security columns)
          const result = await pool.query(
            `SELECT id, email, password_hash, org_id, role, two_factor_enabled, totp_secret 
             FROM users WHERE email = $1`,
            [credentials.email],
          );

          if (result.rows.length === 0) {
            // Delay to prevent timing attacks
            await new Promise(r => setTimeout(r, 100));
            return null;
          }

          const user = result.rows[0];

          // Verify password
          const isValid = await bcrypt.compare(
            credentials.password,
            user.password_hash,
          );

          if (!isValid) {
            // Record the failed attempt
            await recordFailedLoginAttempt(credentials.email);
            return null;
          }

          // Clear failed login attempts on successful auth
          await clearFailedLoginAttempts(credentials.email);

          // Check if 2FA is enabled
          if (user.two_factor_enabled) {
            // Return partial user - require 2FA code
            return {
              id: user.id,
              email: user.email,
              orgId: user.org_id,
              role: user.role,
              requires2FA: true,
            };
          }

          // Return user object (will be encoded in JWT)
          return {
            id: user.id,
            email: user.email,
            orgId: user.org_id,
            role: user.role,
          } as User;
        } catch (error) {
          console.error("Authentication error:", error);
          return null;
        }
      },
    }),
  ],
  session: {
    strategy: "jwt",
    maxAge: 24 * 60 * 60, // 24 hours (reduced from 30 days for security)
  },
  cookies: {
    sessionToken: {
      name: process.env.NODE_ENV === "production" ? "__Secure-session-token" : "session-token",
      options: {
        httpOnly: true,
        secure: process.env.NODE_ENV === "production",
        sameSite: "lax",
        path: "/",
        maxAge: 24 * 60 * 60,
      },
    },
  },
  callbacks: {
    async signIn({ user, account, profile }) {
      // Audit log the sign in attempt
      try {
        const { logAudit } = await import("@/lib/audit");

        await logAudit({
          action:
            account?.provider === "credentials" ? "user_login" : "user_login",
          userId: user.id,
          metadata: {
            provider: account?.provider,
            email: user.email,
          },
        });
      } catch (auditError) {
        console.error("Audit logging error:", auditError);
      }
      // Handle OAuth sign-ins (Google, GitHub)
      if (account?.provider === "google" || account?.provider === "github") {
        try {
          const email = user.email;
          if (!email) {
            return false;
          }

          // Check if user exists
          const existingUser = await pool.query(
            "SELECT id, org_id, role FROM users WHERE email = $1",
            [email.toLowerCase()],
          );

          if (existingUser.rows.length > 0) {
            // User exists, attach org info to user object
            user.id = existingUser.rows[0].id;
            user.orgId = existingUser.rows[0].org_id;
            user.role = existingUser.rows[0].role;
            return true;
          }

          // New OAuth user - create org and user
          const client = await pool.connect();
          try {
            await client.query("BEGIN");

            // Create organization based on email domain or default name
            const orgName = user.name
              ? `${user.name.split(" ")[0]}'s Organization`
              : email.includes("@")
                ? email.split("@")[1].split(".")[0] + " Team"
                : "My Organization";

            const orgId = uuidv4();
            await client.query(
              "INSERT INTO organizations (id, name) VALUES ($1, $2)",
              [orgId, orgName],
            );

            // Create user as admin of their new org
            const userId = uuidv4();
            await client.query(
              `INSERT INTO users (id, org_id, email, name, role)
               VALUES ($1, $2, $3, $4, $5)`,
              [userId, orgId, email.toLowerCase(), user.name ?? null, "admin"],
            );

            await client.query("COMMIT");

            // Attach new user info to session
            user.id = userId;
            user.orgId = orgId;
            user.role = "admin";
            return true;
          } catch (txError) {
            await client.query("ROLLBACK");
            console.error("Error creating OAuth user:", txError);
            return false;
          } finally {
            client.release();
          }
        } catch (error) {
          console.error("OAuth signIn error:", error);
          return false;
        }
      }
      return true;
    },
    async jwt({ token, user, trigger, session }) {
      // Initial sign in - attach user data to token
      if (user) {
        const oauthUser = user as OAuthUser & { requires2FA?: boolean };
        token.id = oauthUser.id ?? token.id;
        token.orgId = oauthUser.orgId ?? token.orgId;
        token.role = oauthUser.role ?? token.role;

        // Mark if 2FA verification is pending
        if (oauthUser.requires2FA) {
          token.requires2FA = true;
        }
      }
      // Handle session updates
      if (trigger === "update" && session) {
        token.id = session.id ?? token.id;
        token.orgId = session.orgId ?? token.orgId;
        token.role = session.role ?? token.role;
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        const t = token as JWTtoken & { requires2FA?: boolean };
        (session.user as { id?: string; orgId?: string; role?: string }).id =
          t.id;
        (session.user as { id?: string; orgId?: string; role?: string }).orgId =
          t.orgId;
        (session.user as { id?: string; orgId?: string; role?: string }).role =
          t.role;

        // If 2FA is required but not verified, deny access
        if (t.requires2FA) {
          (
            session.user as { requires2FAVerification?: boolean }
          ).requires2FAVerification = true;
        }
      }
      return session;
    },
  },
  pages: {
    signIn: "/auth/signin",
    error: "/auth/error",
  },
  secret: process.env.NEXTAUTH_SECRET,
};
