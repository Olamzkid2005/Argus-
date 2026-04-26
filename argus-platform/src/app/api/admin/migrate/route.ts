/**
 * Admin Migration API - One-time migration to create user_settings table
 * 
 * POST /api/admin/migrate - Run migrations
 * Use ?secret=dev to bypass auth in development
 */
import { NextRequest, NextResponse } from "next/server";
import { requireAuth } from "@/lib/session";
import { pool } from "@/lib/db";

export async function POST(request: NextRequest) {
  try {
    await requireAuth();

    const body = await request.json();
    const migration = body.migration;

    if (migration === "user_settings") {
      // Check if table already exists
      const checkTable = await pool.query(`
        SELECT EXISTS (
          SELECT FROM information_schema.tables 
          WHERE table_schema = 'public' 
          AND table_name = 'user_settings'
        );
      `);
      
      if (checkTable.rows[0].exists) {
        return NextResponse.json({ 
          success: true, 
          message: "user_settings table already exists" 
        });
      }
      
      // Return instructions for manual migration
      return NextResponse.json({ 
        error: "Table does not exist. Run the SQL migration manually.",
        sql: 
`CREATE TABLE IF NOT EXISTS user_settings (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_email VARCHAR(255) NOT NULL,
  key VARCHAR(100) NOT NULL,
  value TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_email, key)
);

CREATE INDEX IF NOT EXISTS idx_user_settings_email ON user_settings(user_email);`
      });
    }

    return NextResponse.json({ error: "Unknown migration" }, { status: 400 });

  } catch (error) {
    console.error("Migration error:", error);
    return NextResponse.json({ 
      error: error instanceof Error ? error.message : "Migration failed" 
    }, { status: 500 });
  }
}
