import { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import GoogleProvider from "next-auth/providers/google";
import GitHubProvider from "next-auth/providers/github";
import bcrypt from "bcryptjs";
import { v4 as uuidv4 } from "uuid";
import { pool } from "@/lib/db";
import { log } from "@/lib/logger";

// Security configuration
const MAX_LOGIN_ATTEMPTS = 5;
const LOCKOUT_DURATION_MINUTES = 15;
const SESSION_MAX_AGE = 24 * 60 * 60; // 24 hours

import Redis from "ioredis";

// Redis client for atomic lockout tracking (H-16)
function getLockoutRedis(): Redis {
  const globalForRedis = globalThis as unknown as { __lockoutRedis?: Redis };
  if (!globalForRedis.__lockoutRedis) {
    globalForRedis.__lockoutRedis = new Redis(process.env.REDIS_URL || "redis://localhost:6379", {
      keyPrefix: "lockout:",
      enableOfflineQueue: false,
      lazyConnect: true,
    });
    globalForRedis.__lockoutRedis.on("error", (err) => {
      console.error("Lockout Redis error:", err);
    });
  }
  return globalForRedis.__lockoutRedis;
}

/**
 * Check if account is locked out — uses atomic Redis INCR with EXPIRE
 * to prevent TOCTOU races between SELECT and UPDATE (H-16).
 *
 * If Redis is unavailable, falls back to database query (non-atomic).
 */
async function checkAccountLockout(
  email: string,
): Promise<{ locked: boolean; reason?: string }> {
  try {
    // Try Redis-based atomic lockout first
    const redis = getLockoutRedis();
    const lockKey = `locked:${email.toLowerCase()}`;
    const lockedUntil = await redis.get(lockKey);
    if (lockedUntil) {
      const remaining = Math.ceil(
        (parseInt(lockedUntil, 10) - Date.now()) / 60000,
      );
      return {
        locked: true,
        reason: `Account locked. Try again in ${Math.max(remaining, 1)} minute(s).`,
      };
    }
    const attemptKey = `attempts:${email.toLowerCase()}`;
    const attempts = await redis.get(attemptKey);
    if (attempts && parseInt(attempts, 10) >= MAX_LOGIN_ATTEMPTS) {
      // Atomically set lockout and reset counter in Lua script
      const lua = `
        redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[2])
        redis.call('DEL', KEYS[2])
        return 1
      `;
      await redis.eval(
        lua,
        2,
        lockKey,
        attemptKey,
        String(Date.now() + LOCKOUT_DURATION_MINUTES * 60 * 1000),
        String(LOCKOUT_DURATION_MINUTES * 60 * 1000),
      );
      return {
        locked: true,
        reason: `Too many failed attempts. Account locked for ${LOCKOUT_DURATION_MINUTES} minutes.`,
      };
    }
    return { locked: false };
  } catch (_redisErr) {
    // Redis unavailable — fall back to database-based check
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
      log.authError("Lockout check error", { error: String(error) });
      // M-22: Fail closed — if we can't verify lockout status, deny login
      // to prevent bypass during database or Redis outages.
      return { locked: true, reason: "Unable to verify account status. Please try again later." };
    }
  }
}

/**
 * Record failed login attempt — uses atomic Redis INCR (H-16).
 * Falls back to database UPDATE if Redis is unavailable.
 */
async function recordFailedLoginAttempt(email: string): Promise<void> {
  try {
    const redis = getLockoutRedis();
    const attemptKey = `attempts:${email.toLowerCase()}`;
    const attempts = await redis.incr(attemptKey);
    if (attempts === 1) {
      await redis.pexpire(attemptKey, LOCKOUT_DURATION_MINUTES * 60 * 1000);
    }

    if (attempts >= MAX_LOGIN_ATTEMPTS) {
      const lockKey = `locked:${email.toLowerCase()}`;
      const lockLua = `
        redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[2])
        redis.call('DEL', KEYS[2])
        return 1
      `;
      await redis.eval(
        lockLua,
        2,
        lockKey,
        attemptKey,
        String(Date.now() + LOCKOUT_DURATION_MINUTES * 60 * 1000),
        String(LOCKOUT_DURATION_MINUTES * 60 * 1000),
      );
    }
  } catch {
    // Redis unavailable — fall back to database-based recording
    try {
      const result = await pool.query(
        `SELECT failed_login_attempts FROM users WHERE email = $1`,
        [email.toLowerCase()],
      );

      if (result.rows.length > 0) {
        const attempts = (result.rows[0].failed_login_attempts || 0) + 1;

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
      log.authError("Failed to record login attempt", { error: String(error) });
    }
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
    log.authError("Failed to clear login attempts", { error: String(error) });
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
            `SELECT id, email, password_hash, org_id, role, two_factor_enabled, totp_secret, email_verified 
             FROM users WHERE email = $1`,
            [credentials.email.toLowerCase()],
          );

          if (result.rows.length === 0) {
            // Delay to prevent timing attacks
            await new Promise(r => setTimeout(r, 100));
            return null;
          }

          const user = result.rows[0];

          // H-06: Check if email is verified — unverified users cannot sign in
          if (!user.email_verified) {
            throw new Error(
              "EMAIL_NOT_VERIFIED:Please verify your email before signing in. " +
              "Check your inbox for the verification code, or request a new one."
            );
          }

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
          log.authError("Authentication error", { error: String(error) });
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
        sameSite: "strict",  // H-05: Strictest CSRF protection — cookie not sent cross-origin
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
        log.authError("Audit logging error", { error: String(auditError) });
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

            // Create user as admin of their new org — email_verified = false (H-06)
            const userId = uuidv4();
            await client.query(
              `INSERT INTO users (id, org_id, email, name, role, email_verified)
               VALUES ($1, $2, $3, $4, $5, $6)`,
              [userId, orgId, email.toLowerCase(), user.name ?? null, "admin", false],
            );

            await client.query("COMMIT");

            // H-06: Send verification email for OAuth signups
            // Use dynamic import to avoid top-level side effects
            const crypto = await import("crypto");
            const { sendVerificationEmail } = await import("@/lib/email");

            const verifyToken = crypto.default.randomBytes(32).toString("hex");
            const tokenHash = crypto.default.createHash("sha256").update(verifyToken).digest("hex");
            const expiresAt = new Date(Date.now() + 24 * 60 * 60 * 1000);

            const emailResult = await sendVerificationEmail(
              email.toLowerCase(),
              verifyToken,
            );

            if (emailResult.success) {
              // Store token hash only after successful email delivery
              await pool.query(
                `UPDATE users
                 SET email_verification_token = $1,
                     email_verification_token_expires = $2
                 WHERE id = $3`,
                [tokenHash, expiresAt, userId],
              );
            } else {
              log.authError("Failed to send verification email to OAuth user", {
                email: email.toLowerCase(),
                error: emailResult.error,
              });
            }

            // Attach new user info to session
            user.id = userId;
            user.orgId = orgId;
            user.role = "admin";

            // NOTE: OAuth users can still sign in immediately but should verify
            // their email for sensitive operations. The verification email is
            // sent as a best-effort measure (H-06).
            return true;
          } catch (txError) {
            await client.query("ROLLBACK");
            log.authError("Error creating OAuth user", { error: String(txError) });
            return false;
          } finally {
            client.release();
          }
        } catch (error) {
          log.authError("OAuth signIn error", { error: String(error) });
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
        // Clear requires2FA flag when 2FA verification completes (H-18)
        if (session.requires2FA === false) {
          delete (token as { requires2FA?: boolean }).requires2FA;
        }
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
