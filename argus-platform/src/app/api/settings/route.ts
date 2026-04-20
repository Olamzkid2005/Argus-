/**
 * Settings API - Store and retrieve user API keys
 * 
 * GET /api/settings - Get all settings
 * PUT /api/settings - Update settings including API keys
 */
import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import { sql } from "@/lib/db";

// GET - retrieve settings
export async function GET() {
  try {
    const session = await getServerSession(authOptions);
    
    if (!session?.user?.email) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    
    // Get settings from database
    const result = await sql`
      SELECT key, value 
      FROM user_settings 
      WHERE user_email = ${session.user.email}
    `;
    
    // Convert to object
    const settings: Record<string, string> = {};
    for (const row of result) {
      settings[row.key] = row.value;
    }
    
    // Don't return actual API keys - mask them
    if (settings.openai_api_key) {
      settings.openai_api_key = settings.openai_api_key.startsWith("sk-") 
        ? "sk-" + "•".repeat(20) 
        : "•".repeat(24);
    }
    if (settings.opencode_api_key) {
      settings.opencode_api_key = "•".repeat(24);
    }
    
    return NextResponse.json({ settings });
  } catch (error) {
    console.error("Settings GET error:", error);
    return NextResponse.json({ error: "Failed to get settings" }, { status: 500 });
  }
}

// PUT - update settings
export async function PUT(request: NextRequest) {
  try {
    const session = await getServerSession(authOptions);
    
    if (!session?.user?.email) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    
    const body = await request.json();
    const { openai_api_key, opencode_api_key, ...otherSettings } = body;
    
    // Update each provided setting
    const settingsToUpdate = [
      { key: "openai_api_key", value: openai_api_key },
      { key: "opencode_api_key", value: opencode_api_key },
      ...Object.entries(otherSettings).map(([key, value]) => ({ key, value: String(value) })),
    ];
    
    for (const setting of settingsToUpdate) {
      if (setting.value !== undefined && setting.value !== null && setting.value !== "") {
        // Upsert - insert or update
        await sql`
          INSERT INTO user_settings (user_email, key, value)
          VALUES (${session.user.email}, ${setting.key}, ${setting.value})
          ON CONFLICT (user_email, key) DO UPDATE SET value = ${setting.value}
        `;
      }
    }
    
    return NextResponse.json({ success: true });
  } catch (error) {
    console.error("Settings PUT error:", error);
    return NextResponse.json({ error: "Failed to update settings" }, { status: 500 });
  }
}