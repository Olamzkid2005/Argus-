/**
 * Settings API - In-memory settings (stored in Redis for now)
 * 
 * GET /api/settings - Get all settings
 * PUT /api/settings - Update settings including API keys
 */
import { NextRequest, NextResponse } from "next/server";
import { getServerSession } from "next-auth";
import { authOptions } from "@/lib/auth";
import Redis from "ioredis";

// Redis client for settings storage
function getRedisClient() {
  const redisUrl = process.env.REDIS_URL || "redis://localhost:6379";
  return new Redis(redisUrl, { 
    maxRetriesPerRequest: 1,
    lazyConnect: true 
  });
}

// GET - retrieve settings from Redis
export async function GET() {
  let redis: Redis | null = null;
  
  try {
    const session = await getServerSession(authOptions);
    
    if (!session?.user?.email) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    
    const email = session.user.email;
    redis = getRedisClient();
    
    const openaiKey = await redis.get(`settings:${email}:openai_api_key`);
    const opencodeKey = await redis.get(`settings:${email}:opencode_api_key`);
    
    const settings: Record<string, string> = {};
    
    // Mask the keys
    if (openaiKey) {
      settings.openai_api_key = openaiKey.startsWith("sk-") 
        ? "sk-" + "•".repeat(20) 
        : "•".repeat(24);
    }
    if (opencodeKey) {
      settings.opencode_api_key = "•".repeat(24);
    }
    
    return NextResponse.json({ settings });
    
  } catch (error) {
    console.error("Settings GET error:", error);
    return NextResponse.json({ error: "Failed to get settings" }, { status: 500 });
  } finally {
    if (redis) {
      redis.disconnect();
    }
  }
}

// PUT - update settings in Redis
export async function PUT(request: NextRequest) {
  let redis: Redis | null = null;
  
  try {
    const session = await getServerSession(authOptions);
    
    if (!session?.user?.email) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    
    const body = await request.json();
    const { openai_api_key, opencode_api_key, ...otherSettings } = body;
    const email = session.user.email;
    
    redis = getRedisClient();
    
    // Store keys (if not masked with •)
    if (openai_api_key && openai_api_key.length > 5 && !openai_api_key.includes("•")) {
      await redis.setex(`settings:${email}:openai_api_key`, 86400, openai_api_key);
    }
    
    if (opencode_api_key && opencode_api_key.length > 5 && !opencode_api_key.includes("•")) {
      await redis.setex(`settings:${email}:opencode_api_key`, 86400, opencode_api_key);
    }
    
    // Store other settings
    for (const [key, value] of Object.entries(otherSettings)) {
      if (value && typeof value === "string" && value.length > 0) {
        await redis.setex(`settings:${email}:${key}`, 86400, value);
      }
    }
    
    return NextResponse.json({ success: true });
    
  } catch (error) {
    console.error("Settings PUT error:", error);
    return NextResponse.json({ error: "Failed to update settings" }, { status: 500 });
  } finally {
    if (redis) {
      redis.disconnect();
    }
  }
}