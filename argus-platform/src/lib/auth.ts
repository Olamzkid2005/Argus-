import { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import GoogleProvider from "next-auth/providers/google";
import GitHubProvider from "next-auth/providers/github";
import { Pool } from "pg";
import bcrypt from "bcryptjs";
import { v4 as uuidv4 } from "uuid";

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

// PostgreSQL connection pool
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

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
          // Query user from database
          const result = await pool.query(
            "SELECT id, email, password_hash, org_id, role FROM users WHERE email = $1",
            [credentials.email]
          );

          if (result.rows.length === 0) {
            return null;
          }

          const user = result.rows[0];

          // Verify password
          const isValid = await bcrypt.compare(
            credentials.password,
            user.password_hash
          );

          if (!isValid) {
            return null;
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
    maxAge: 30 * 24 * 60 * 60, // 30 days
  },
  callbacks: {
    async signIn({ user, account }) {
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
            [email.toLowerCase()]
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
              [orgId, orgName]
            );

            // Create user as admin of their new org
            const userId = uuidv4();
            await client.query(
              `INSERT INTO users (id, org_id, email, name, role)
               VALUES ($1, $2, $3, $4, $5)`,
              [userId, orgId, email.toLowerCase(), user.name ?? null, "admin"]
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
        const oauthUser = user as OAuthUser;
        token.id = oauthUser.id ?? token.id;
        token.orgId = oauthUser.orgId ?? token.orgId;
        token.role = oauthUser.role ?? token.role;
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
        const t = token as JWTtoken;
        (session.user as { id?: string; orgId?: string; role?: string }).id = t.id;
        (session.user as { id?: string; orgId?: string; role?: string }).orgId = t.orgId;
        (session.user as { id?: string; orgId?: string; role?: string }).role = t.role;
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